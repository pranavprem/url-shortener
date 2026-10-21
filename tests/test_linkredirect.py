"""Tests for the redirect handler and optional hit logging."""

from unittest.mock import Mock

from botocore.exceptions import ClientError

from linkredirect import service
from local_server import MemoryTable


def _table_with(code, url):
    table = MemoryTable()
    table.put_item(
        TableName="urls",
        Item={"shorturl": {"S": code}, "url": {"S": url}},
    )
    return table


def _event(code):
    return {"params": {"path": {"shorturl": code}}}


def test_redirect_keeps_the_stored_scheme():
    table = _table_with("abc", "https://example.com/a")

    result = service.handler(_event("abc"), None, dynamodb_client=table)

    assert result == {"Location": "https://example.com/a"}


def test_legacy_schemeless_rows_redirect_over_http():
    table = _table_with("abc", "example.com/a")

    result = service.handler(_event("abc"), None, dynamodb_client=table)

    assert result == {"Location": "http://example.com/a"}


def test_unknown_code_returns_an_error_and_does_not_log():
    search = Mock()

    result = service.handler(
        _event("missing"),
        None,
        dynamodb_client=MemoryTable(),
        search_client=search,
    )

    assert result == {"error": "short url not found"}
    search.index.assert_not_called()


def test_missing_shorturl_returns_an_error():
    result = service.handler({}, None, dynamodb_client=MemoryTable())
    assert result == {"error": "missing shorturl"}
    malformed = service.handler(
        {"params": "nope"},
        None,
        dynamodb_client=MemoryTable(),
    )
    assert malformed == {"error": "missing shorturl"}


def test_dynamodb_errors_become_an_error_response():
    client = Mock()
    client.get_item.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "nope"}},
        "GetItem",
    )

    result = service.handler(_event("abc"), None, dynamodb_client=client)

    assert result == {"error": "could not look up url"}


def test_search_failure_still_redirects():
    table = _table_with("abc", "https://example.com/a")
    search = Mock()
    search.index.side_effect = RuntimeError("cluster down")

    result = service.handler(
        _event("abc"),
        None,
        dynamodb_client=table,
        search_client=search,
    )

    assert result == {"Location": "https://example.com/a"}


def test_hit_is_indexed_as_a_document(monkeypatch):
    monkeypatch.setenv("ELASTICSEARCH_INDEX", "hits")
    table = _table_with("abc", "https://example.com/a")
    search = Mock()
    event = _event("abc")

    service.handler(event, None, dynamodb_client=table, search_client=search)

    search.index.assert_called_once_with(index="hits", body=event)


def test_logging_is_skipped_when_unconfigured(monkeypatch):
    monkeypatch.delenv("ELASTICSEARCH_URL", raising=False)
    table = _table_with("abc", "https://example.com/a")

    result = service.handler(_event("abc"), None, dynamodb_client=table)

    assert result["Location"] == "https://example.com/a"


def test_build_search_client_for_a_local_cluster(monkeypatch):
    created = {}

    class FakeOpenSearch:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr("opensearchpy.OpenSearch", FakeOpenSearch)
    monkeypatch.setattr(
        "opensearchpy.RequestsHttpConnection",
        lambda: None,
    )

    service.build_search_client("http://localhost:9200")

    assert created["hosts"] == [{"host": "localhost", "port": 9200}]
    assert created["use_ssl"] is False
    assert "http_auth" not in created


def test_build_search_client_signs_aws_hosts(monkeypatch):
    created = {}

    class FakeOpenSearch:
        def __init__(self, **kwargs):
            created.update(kwargs)

    class Credentials:
        def get_frozen_credentials(self):
            return self

    class Session:
        def get_credentials(self):
            return Credentials()

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr("opensearchpy.OpenSearch", FakeOpenSearch)
    monkeypatch.setattr("opensearchpy.RequestsHttpConnection", lambda: None)
    monkeypatch.setattr(service.boto3, "Session", Session)

    service.build_search_client("https://search-example.us-west-1.es.amazonaws.com")

    assert created["hosts"] == [
        {"host": "search-example.us-west-1.es.amazonaws.com", "port": 443}
    ]
    assert created["use_ssl"] is True
    assert created["http_auth"] is not None


def test_region_can_be_read_from_an_old_domain_name(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    hostname = "search-example.us-west-1.es.amazonaws.com"
    assert service._region_for_host(hostname) == "us-west-1"
    assert service._region_for_host("localhost") is None
