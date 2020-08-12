FROM python:3.8-alpine
LABEL maintainer="Keyko <root@keyko.io>"

ARG VERSION

RUN apk add --no-cache --update \
    build-base \
    gcc \
    libffi-dev \
    openssl-dev

RUN pip install nevermined-sdk-py web3

COPY . /nevermined-pod-publishing
WORKDIR /nevermined-pod-publishing

RUN pip install .
RUN pip install contracts-lib-py==0.2.4
RUN pip freeze

ENTRYPOINT pod-publishing --help
