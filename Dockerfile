FROM python:3-alpine

RUN apk add git git-svn subversion bash \
    && mkdir /root/data

VOLUME [ "/root/data", "/root" ]

