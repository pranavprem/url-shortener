"""The local server exercises both handlers without AWS."""

import http.client
import json
import threading

from local_server import make_server


def _start():
    server = make_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server, thread):
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def test_create_and_redirect_round_trip():
    server, thread = _start()
    host, port = server.server_address
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request(
            "POST",
            "/",
            body=json.dumps({"url": "https://example.com/docs"}),
        )
        created = connection.getresponse()
        payload = json.loads(created.read().decode())
        assert created.status == 200
        assert payload["url"] == "https://example.com/docs"

        connection.request("GET", "/" + payload["shorturl"])
        redirected = connection.getresponse()
        redirected.read()
        assert redirected.status == 302
        assert redirected.getheader("Location") == "https://example.com/docs"
    finally:
        _stop(server, thread)


def test_unknown_code_is_not_found():
    server, thread = _start()
    host, port = server.server_address
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("GET", "/does-not-exist")
        response = connection.getresponse()
        body = json.loads(response.read().decode())
        assert response.status == 404
        assert body["error"] == "short url not found"
    finally:
        _stop(server, thread)


def test_invalid_url_is_rejected():
    server, thread = _start()
    host, port = server.server_address
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("POST", "/", body=json.dumps({"url": "javascript:alert(1)"}))
        response = connection.getresponse()
        body = json.loads(response.read().decode())
        assert response.status == 400
        assert "error" in body
    finally:
        _stop(server, thread)
