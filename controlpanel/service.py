"""Create short URLs and store them in DynamoDB."""

import logging
import os
import uuid
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

MAX_URL_LENGTH = 4096


def normalize_url(url):
    """Return an absolute http(s) URL, preserving an existing scheme.

    A value with no scheme is treated as https. Legacy rows created by the
    2017 function stored the host without a scheme; new rows keep it.
    """
    if not isinstance(url, str):
        raise ValueError("url must be a string")
    cleaned = url.strip()
    if not cleaned or any(character.isspace() for character in cleaned):
        raise ValueError("url must be a non-empty URL without spaces")
    if len(cleaned) > MAX_URL_LENGTH:
        raise ValueError("url is too long")

    parsed = urlparse(cleaned)
    if parsed.scheme == "" and parsed.netloc == "":
        parsed = urlparse("https://" + cleaned)
    elif parsed.scheme == "" and parsed.netloc:
        parsed = urlparse("https:" + cleaned)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("url must be an absolute http(s) URL")
    return parsed.geturl()


def handler(event, context, dynamodb_client=None):
    """Store a destination URL and return its short code.

    ``event`` is ``{"url": "<destination>"}``, the shape the original API
    Gateway mapping passed in. ``dynamodb_client`` defaults to a boto3
    DynamoDB client; tests and the local server inject their own.
    """
    del context  # Lambda supplies this; the function does not use it.
    if not isinstance(event, dict) or "url" not in event:
        return {"error": "missing url"}

    try:
        url = normalize_url(event["url"])
    except ValueError as exc:
        return {"error": str(exc)}

    shorturl = uuid.uuid4().hex
    client = dynamodb_client or boto3.client("dynamodb")
    table_name = os.environ.get("DYNAMODB_TABLE", "urls")
    try:
        client.put_item(
            TableName=table_name,
            Item={
                "shorturl": {"S": shorturl},
                "url": {"S": url},
            },
        )
    except (ClientError, BotoCoreError):
        logger.exception("failed to store short url")
        return {"error": "could not store url"}

    return {"url": url, "shorturl": shorturl}
