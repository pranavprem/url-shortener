"""Resolve a short code and return the redirect destination."""

import logging
import os
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


def redirect_location(stored):
    """Build the Location value for a URL stored in DynamoDB.

    Rows written by the current function already include a scheme. Rows
    written by the 2017 function stored a bare host, and those still
    redirect over http, which is what that function always did.
    """
    parsed = urlparse(stored)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return stored
    return "http://" + stored


def _shorturl_from_event(event):
    if not isinstance(event, dict):
        return None
    params = event.get("params") or {}
    if not isinstance(params, dict):
        return None
    path = params.get("path") or {}
    if not isinstance(path, dict):
        return None
    shorturl = path.get("shorturl")
    if isinstance(shorturl, str) and shorturl.strip():
        return shorturl.strip()
    return None


def _region_for_host(hostname):
    """Region used to sign requests to an AWS OpenSearch domain."""
    if not hostname.endswith(".amazonaws.com"):
        return None
    configured = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if configured:
        return configured
    suffix = ".es.amazonaws.com"
    if hostname.endswith(suffix):
        prefix = hostname[: -len(suffix)]
        if "." in prefix:
            return prefix.rsplit(".", 1)[-1]
    return None


def _aws_auth(hostname):
    region = _region_for_host(hostname)
    if region is None:
        return None
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        logger.warning("not signing OpenSearch request; no AWS credentials")
        return None
    from opensearchpy import AWSV4SignerAuth

    return AWSV4SignerAuth(credentials, region, "es")


def build_search_client(url):
    """Open a client for ``ELASTICSEARCH_URL``.

    Amazon OpenSearch hosts (``*.amazonaws.com``) are signed with SigV4
    using the default AWS credential chain. Other hosts are unsigned, so a
    local cluster works without credentials.
    """
    from opensearchpy import OpenSearch, RequestsHttpConnection

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("ELASTICSEARCH_URL must be an http(s) URL")
    use_ssl = parsed.scheme == "https"
    port = parsed.port or (443 if use_ssl else 9200)
    kwargs = {
        "hosts": [{"host": parsed.hostname, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": use_ssl,
        "connection_class": RequestsHttpConnection,
    }
    auth = _aws_auth(parsed.hostname)
    if auth is not None:
        kwargs["http_auth"] = auth
    return OpenSearch(**kwargs)


def _record_hit(event, search_client):
    """Index the invoke event. Failures are logged and then ignored."""
    if search_client is None:
        endpoint = os.environ.get("ELASTICSEARCH_URL", "").strip()
        if not endpoint:
            return
        try:
            search_client = build_search_client(endpoint)
        except Exception:
            logger.exception("failed to create search client")
            return

    index = os.environ.get("ELASTICSEARCH_INDEX", "urls")
    body = event if isinstance(event, dict) else {"event": str(event)}
    try:
        search_client.index(index=index, body=body)
    except Exception:
        logger.exception("failed to record redirect hit")


def handler(event, context, dynamodb_client=None, search_client=None):
    """Look up ``event["params"]["path"]["shorturl"]`` and return a Location.

    The return value is ``{"Location": "<url>"}`` for API Gateway to map
    onto a 302. A search client is optional. When ``ELASTICSEARCH_URL`` is
    unset and no client is injected, hit logging is skipped. A logging
    failure does not block the redirect.
    """
    del context
    shorturl = _shorturl_from_event(event)
    if shorturl is None:
        return {"error": "missing shorturl"}

    client = dynamodb_client or boto3.client("dynamodb")
    table_name = os.environ.get("DYNAMODB_TABLE", "urls")
    try:
        item = client.get_item(
            TableName=table_name,
            Key={"shorturl": {"S": shorturl}},
        )
    except (ClientError, BotoCoreError):
        logger.exception("failed to look up short url")
        return {"error": "could not look up url"}

    stored = (item.get("Item") or {}).get("url", {}).get("S")
    if not stored:
        return {"error": "short url not found"}

    _record_hit(event, search_client)
    return {"Location": redirect_location(stored)}
