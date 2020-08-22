import argparse
import json
import logging
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
import time

from minio import Minio
from nevermined_sdk_py import Config, Nevermined
from nevermined_sdk_py.nevermined.accounts import Account
from web3 import Web3


def run(args):
    logging.debug(f"script callef with args: {args}")

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

    # get files to upload
    files = []
    index = 0
    for f in outputs_path.rglob("*"):
        if f.is_file():
            renamed_file = Path(f.parent) / f"{uuid.uuid4()}-{f.name}"
            f.rename(renamed_file)
            files.append(
                {
                    "index": index,
                    "name": renamed_file.name,
                    "path": renamed_file.as_posix(),
                    "contentType": mimetypes.guess_type(renamed_file)[0],
                    "contentLength": renamed_file.stat().st_size,
                }
            )
            index += 1

    # create bucket
    minio_client = Minio(
        "argo-artifacts.default:9000",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        secure=False,
    )
    bucket_name = f"pod-publishing-{str(uuid.uuid4())}"
    minio_client.make_bucket(bucket_name, location="eu-central-1")
    logging.info(f"Created bucket {bucket_name}")

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
            "metadata": workflow.metadata,
            "files": files,
            "type": "dataset",
        }
    }

    ddo = None
    while ddo is None:
        try:
            ddo = nevermined.assets.create(
                metadata,
                account,
                providers=[account.address],
                # authorization_type="SecretStore",
            )
        except ValueError:
            logging.info("retrying creation of asset")
            time.sleep(10)
    logging.info(f"Publishing {ddo.did}")
    logging.debug(f"Publishing ddo: {ddo}")


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
