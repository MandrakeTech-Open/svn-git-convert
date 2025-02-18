FROM python:3-alpine

RUN apk add git git-svn subversion bash \
    && mkdir -p /workspace/data

VOLUME [ "/workspace/data", "/workspace" ]

