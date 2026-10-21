"""Tests for the short-URL creation handler."""

import uuid
from unittest.mock import Mock

from botocore.exceptions import ClientError

from controlpanel import service
from local_server import MemoryTable


def test_normalize_preserves_https_and_http():
    assert service.normalize_url("https://example.com/a") == "https://example.com/a"
    assert service.normalize_url("http://example.com/a") == "http://example.com/a"


def test_normalize_adds_https_when_scheme_is_missing():
    assert service.normalize_url("example.com/docs") == "https://example.com/docs"
    assert service.normalize_url("//example.com/docs") == "https://example.com/docs"


def test_normalize_rejects_non_http_urls():
    for value in ("", "   ", "javascript:alert(1)", "ftp://example.com", "not a url"):
        try:
            service.normalize_url(value)
        except ValueError:
            continue
        raise AssertionError(value)


def test_handler_stores_full_url_and_returns_a_code(monkeypatch):
    monkeypatch.setattr(service.uuid, "uuid4", lambda: uuid.UUID(int=1))
    monkeypatch.delenv("DYNAMODB_TABLE", raising=False)
    table = MemoryTable()

    result = service.handler(
        {"url": "https://example.com/docs"},
        None,
        dynamodb_client=table,
    )

    assert result == {
        "url": "https://example.com/docs",
        "shorturl": uuid.UUID(int=1).hex,
    }
    stored = table.get_item(
        TableName="urls", Key={"shorturl": {"S": result["shorturl"]}}
    )
    assert stored["Item"]["url"]["S"] == "https://example.com/docs"


def test_handler_uses_table_name_from_the_environment(monkeypatch):
    monkeypatch.setenv("DYNAMODB_TABLE", "custom")
    client = Mock()

    service.handler({"url": "https://example.com"}, None, dynamodb_client=client)

    assert client.put_item.call_args.kwargs["TableName"] == "custom"


def test_handler_returns_an_error_when_dynamodb_fails():
    client = Mock()
    client.put_item.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "slow down"}},
        "PutItem",
    )

    result = service.handler(
        {"url": "https://example.com"},
        None,
        dynamodb_client=client,
    )

    assert result == {"error": "could not store url"}
    assert "slow down" not in result["error"]


def test_handler_rejects_a_missing_or_invalid_url():
    assert service.handler({}, None, dynamodb_client=MemoryTable()) == {
        "error": "missing url"
    }
    result = service.handler(
        {"url": "javascript:alert(1)"},
        None,
        dynamodb_client=MemoryTable(),
    )
    assert result == {"error": "url must be an absolute http(s) URL"}
