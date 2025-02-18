FROM python:3-alpine

RUN apk add git git-svn subversion bash \
    && mkdir /workspace/data

VOLUME [ "/workspace/data", "/workspace" ]

