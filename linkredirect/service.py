# -*- coding: utf-8 -*-
"""Module that implements a link redirect engine for url shortener"""
import boto3

def handler(event, context):
    """Event handler in lambda context"""
    url = event["url"]
    client = boto3.client("dynamodb")

    try:
        item = client.get_item(TableName="urls", Key={
            "shorturl" : {"S":url}
        })
    except Exception, exception:
        return exception

    return {"Location":"http://"+item["Item"]["url"]["S"]}
