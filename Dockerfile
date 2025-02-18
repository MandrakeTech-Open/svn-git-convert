FROM python:3-alpine

RUN apk add git git-svn subversion bash openssh-client \
    && mkdir -p /workspace/data

VOLUME [ "/workspace/data", "/workspace" ]

