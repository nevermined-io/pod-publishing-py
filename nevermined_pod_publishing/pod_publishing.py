import argparse
import json
import logging
import mimetypes
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from minio import Minio
from nevermined_sdk_py import Config, Nevermined
from nevermined_sdk_py.nevermined.accounts import Account
from contracts_lib_py.utils import add_ethereum_prefix_and_hash_msg
from web3 import Web3
from common_utils_py.did import convert_to_bytes, DID


def s3_readonly_policy(bucket_name):
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{bucket_name}"],
            },
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket_name}/*"],
            },
        ],
    }
    return json.dumps(policy)


def run(args):
    logging.debug(f"script called with args: {args}")

    # setup config
    options = {
        "keeper-contracts": {
            "keeper.url": args.node,
            "secret_store.url": args.secretstore_url,
        },
        "resources": {
            "downloads.path": args.path.as_posix(),
            "metadata.url": args.metadata_url,
            "gateway.url": args.gateway_url,
        },
    }
    config = Config(options_dict=options)
    logging.debug(f"nevermined config: {config}")

    # setup paths
    outputs_path = args.path / "outputs"

    # setup nevermined
    nevermined = Nevermined(config)

    # setup consumer
    # here we need to create a temporary key file from the credentials
    key_file = NamedTemporaryFile("w", delete=False)
    json.dump(args.credentials, key_file)
    key_file.flush()
    key_file.close()
    account = Account(
        Web3.toChecksumAddress(args.credentials["address"]),
        password=args.password,
        key_file=key_file.name,
    )

    # resolve workflow
    workflow = nevermined.assets.resolve(args.workflow)
    logging.info(f"resolved workflow {args.workflow}")
    logging.debug(f"workflow ddo {workflow.as_dictionary()}")

    workflow_owner = nevermined.assets.owner(workflow.did)
    provenance_id = uuid.uuid4()

    # get files to upload
    files = []
    index = 0
    for f in outputs_path.rglob("*"):
        if f.is_file():
            files.append(
                {
                    "index": index,
                    "name": f.name,
                    "path": f.as_posix(),
                    "contentType": mimetypes.guess_type(f)[0],
                    "contentLength": f.stat().st_size,
                }
            )
            index += 1

    # create bucket
    minio_client = Minio(
        "172.17.0.1:8060",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        secure=False,
    )
    bucket_name = f"pod-publishing-{str(uuid.uuid4())}"
    minio_client.make_bucket(bucket_name, location="eu-central-1")
    logging.info(f"Created bucket {bucket_name}")
    minio_client.set_bucket_policy(bucket_name, s3_readonly_policy(bucket_name))
    logging.info(f"Set bucket {bucket_name} policy to READ_ONLY")
    nevermined.provenance.used(provenance_id=Web3.toBytes(provenance_id.bytes),
                               did=convert_to_bytes(workflow.did),
                               agent_id=convert_to_bytes(workflow_owner),
                               activity_id=convert_to_bytes(nevermined._web3.keccak(text='compute')),
                               signature=nevermined.keeper.sign_hash(add_ethereum_prefix_and_hash_msg(str(provenance_id)), account=account),
                               account=account,
                               attributes='compute'
                               )

    # upload files
    for f in files:
        minio_client.fput_object(bucket_name, f["name"], f["path"])
        logging.info(f"Uploaded file {f['path']}")

        del f["path"]
        f["url"] = minio_client.presigned_get_object(bucket_name, f["name"])
        logging.info(f"File url {f['url']}")

    # Create ddo
    publishing_date = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    metadata = {
        "main": {
            "dateCreated": publishing_date,
            "datePublished": publishing_date,
            "author": "pod-publishing",
            "license": "No License Specified",
            "price": "1",
            "metadata": {
                "workflow": workflow.metadata,
                "executionId": os.getenv("EXECUTION_ID"),
            },
            "files": files,
            "type": "dataset",
        }
    }

    # publish the ddo
    ddo = None
    retry = 0
    while ddo is None:
        try:
            ddo = nevermined.assets.create(
                metadata, account, providers=[account.address],
            )
            nevermined.provenance.was_derived_from(provenance_id=Web3.toBytes(provenance_id.bytes),
                                                   new_entity_did=convert_to_bytes(ddo.did),
                                                   used_entity_did=convert_to_bytes(workflow.did),
                                                   agent_id=convert_to_bytes(workflow_owner),
                                                   activity_id=convert_to_bytes(nevermined._web3.keccak(text='published')),
                                                   account=account,
                                                   attributes='published')
        except ValueError:
            if retry == 3:
                raise
            logging.warning("retrying creation of asset")
            retry += 1
            time.sleep(30)
    logging.info(f"Publishing {ddo.did}")
    logging.debug(f"Publishing ddo: {ddo}")

    # transfer ownership to the owner of the workflow
    retry = 0
    while True:
        try:
            nevermined.assets.transfer_ownership(ddo.did, workflow_owner, account)
            nevermined.provenance.was_associated_with(provenance_id=Web3.toBytes(provenance_id.bytes),
                                                      did=workflow.did,
                                                      agent_id=workflow_owner,
                                                      activity_id=convert_to_bytes(nevermined._web3.keccak(text='transferOwnership')),
                                                      account=account,
                                                      attributes='transferOwnership')
        except ValueError:
            if retry == 3:
                raise
            logging.warning("retrying transfer of ownership")
            retry += 1
            time.sleep(30)
        else:
            break
    logging.info(
        f"Transfered ownership of {workflow.did} from {account.address} to {workflow_owner}"
    )


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_argument_group("required arguments")

    group.add_argument("-w", "--workflow", help="Workflow did", required=True)
    group.add_argument("-n", "--node", help="Node URL", required=True)
    group.add_argument("--gateway-url", help="Gateway URL", required=True)
    group.add_argument("--metadata-url", help="Metadata URL", required=True)
    group.add_argument("--secretstore-url", help="Secretstore URL", required=True)
    group.add_argument(
        "-c",
        "--credentials",
        help="Credentials password",
        type=json.loads,
        required=True,
    )
    group.add_argument("-p", "--password", help="Credentials password", required=True)
    group.add_argument("-l", "--path", help="Volume path", type=Path, required=True)
    parser.add_argument(
        "-v", "--verbose", help="Enables verbose mode", action="store_true"
    )
    args = parser.parse_args()

    # setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] (%(name)s) %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    run(args)


if __name__ == "__main__":
    main()
