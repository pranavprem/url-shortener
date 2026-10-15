"""Run the two handlers over HTTP with an in-memory table.

This is a local stand-in for API Gateway and DynamoDB. It listens on
127.0.0.1 and does not call AWS. Hit logging stays off unless a caller
injects a search client, which this server does not.
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from controlpanel.service import handler as create_handler
from linkredirect.service import handler as redirect_handler

logger = logging.getLogger("urlshortener.local")

MAX_BODY_BYTES = 1_000_000


class MemoryTable:
    """The two DynamoDB calls the handlers use."""

    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def put_item(self, TableName, Item):
        del TableName
        with self._lock:
            self._items[Item["shorturl"]["S"]] = Item

    def get_item(self, TableName, Key):
        del TableName
        with self._lock:
            item = self._items.get(Key["shorturl"]["S"])
        if item is None:
            return {}
        return {"Item": item}


class ShortenerHandler(BaseHTTPRequestHandler):
    table = None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/health"):
            self._send(200, {"status": "ok"})
            return
        code = path.strip("/")
        if not code or "/" in code:
            self._send(404, {"error": "not found"})
            return
        result = redirect_handler(
            {"params": {"path": {"shorturl": code}}},
            None,
            dynamodb_client=self.table,
        )
        if "Location" in result:
            body = json.dumps(result).encode()
            self.send_response(302)
            self.send_header("Location", result["Location"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        status = 404 if result.get("error") == "short url not found" else 400
        self._send(status, result)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/", "/shorten"):
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._send(400, {"error": "invalid content length"})
            return
        if length > MAX_BODY_BYTES:
            self._send(400, {"error": "body is too large"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            event = json.loads(raw.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"error": "body must be JSON"})
            return
        if not isinstance(event, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return
        result = create_handler(event, None, dynamodb_client=self.table)
        status = 200 if "shorturl" in result else 400
        self._send(status, result)

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.info("%s - " + fmt, self.address_string(), *args)


def make_server(host="127.0.0.1", port=8000, table=None):
    """Bind a server. ``port=0`` asks the OS for a free port."""
    bound = table or MemoryTable()

    class Handler(ShortenerHandler):
        table = bound

    return ThreadingHTTPServer((host, port), Handler)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    port = int(os.environ.get("PORT", "8000"))
    server = make_server(port=port)
    host, bound_port = server.server_address
    logger.info("listening on http://%s:%s", host, bound_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
