# -*- coding: utf-8 -*-
"""Module that implements a link redirect engine for url shortener"""
import json
import boto3
from elasticsearch import Elasticsearch, RequestsHttpConnection



def handler(event, context):
    """Event handler in lambda context"""
    url = event["params"]["path"]["shorturl"]
    client = boto3.client("dynamodb")
    esEndPoint = "search-url-shortener-t76w2u5nrhzsacc3n2oy3lvozi.us-west-1.es.amazonaws.com"

    try:
        item = client.get_item(TableName="urls", Key={
            "shorturl" : {"S":url}
        })
    except Exception, exception:
        return exception

    try:
        esClient = Elasticsearch(
            hosts=[{'host': esEndPoint, 'port': 443}],
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection
            )
        esClient.index(index="urls", doc_type="hit", body=json.dumps(event))
    except Exception as exception:
        return exception
    return {"Location":"http://"+item["Item"]["url"]["S"]}
