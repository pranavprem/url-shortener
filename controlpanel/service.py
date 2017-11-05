# -*- coding: utf-8 -*-
"""Module that implements a control panel for url shortener"""
import uuid
import boto3


def handler(event, context):
    """Event handler in lambda context"""
    url = event["url"]
    if url.startswith("http://"):
        url = url[7:]
    if url.startswith("https://"):
        url = url[8:]

    client = boto3.client("dynamodb")
    item = {"url":url, "shorturl":str(uuid.uuid4().hex)}
    try:
        client.put_item(TableName="urls", Item={
            "shorturl" :{"S":item["shorturl"]},
            "url": {"S":item["url"]}
        })
    except Exception, exception:
        return exception

    #print("short"+short)
    return item
