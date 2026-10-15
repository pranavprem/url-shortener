# Agent guide

This file is the source of truth for working on the URL shortener. [CLAUDE.md](CLAUDE.md) points here.

## Architecture

Two independent Lambda handlers share one DynamoDB table. They stay in separate directories because each function is deployed as its own zip with handler `service.handler`.

- `controlpanel/service.py` — `handler(event, context, dynamodb_client=None)`. Reads `event["url"]`, normalizes it, writes `{shorturl, url}` with the low-level DynamoDB attribute format (`{"S": ...}`), and returns `{"url", "shorturl"}`.
- `linkredirect/service.py` — `handler(event, context, dynamodb_client=None, search_client=None)`. Reads `event["params"]["path"]["shorturl"]`, loads the row, and returns `{"Location": "<absolute url>"}`. After a successful lookup it may index the invoke event.
- `local_server.py` — development only. `MemoryTable` implements `put_item` and `get_item`. `ThreadingHTTPServer` on `127.0.0.1` turns `POST /` into a create event and `GET /<code>` into a redirect event. It is not a third production entry point.

Neither handler speaks API Gateway's Lambda proxy format (`statusCode` / `body`). Keep returning the plain dicts above so an existing mapping template keeps working.

Short codes are `uuid.uuid4().hex` (32 lowercase hex characters). The table's partition key is `shorturl`.

Hit logging:

- Off unless `ELASTICSEARCH_URL` is set or a test injects `search_client`.
- The client is `opensearch-py`. The import is inside `build_search_client`, so the redirect zip runs without that dependency until logging is enabled.
- Hosts ending in `.amazonaws.com` are signed with `AWSV4SignerAuth` and service name `es`, using the default boto3 credential chain. The region is `AWS_REGION`, then `AWS_DEFAULT_REGION`, then the label before `.es.amazonaws.com`.
- Other hosts are unsigned, on port 443 for `https` and port 9200 for `http` when the URL omits a port.
- Index name is `ELASTICSEARCH_INDEX` or `urls`. The document is the event dict. OpenSearch has no document type; the 2017 `doc_type="hit"` argument is gone.
- Any exception while building the client or indexing is logged and swallowed. The redirect still returns.

`dynamodb_client` and `search_client` exist so tests and the local server never open a real AWS connection. Production calls omit them and the handlers construct boto3 (and, when configured, OpenSearch) themselves.

## Conventions

- Python 3.12. The Lambda runtime in each `config.yaml` is `python3.12`.
- Ruff formats and lints. Config is in `pyproject.toml` (`E`, `F`, `I`, `UP`, `B`; line length 88).
- Direct dependencies are pinned with `==` in `requirements.txt` and `requirements-dev.txt`. Add a runtime import to `requirements.txt` and a test-only tool to `requirements-dev.txt`.
- Handlers return `{"error": "<stable message>"}` for expected failures (bad input, missing row, DynamoDB client errors). Unexpected bugs should propagate so Lambda records them.
- DynamoDB calls stay on the low-level client (`put_item` / `get_item`), which is what the 2017 code used.
- New behavior needs a pytest in `tests/` that injects `MemoryTable` or a `Mock`. Do not let tests call AWS.
- There is no license file. Do not add one.
- Do not commit `.env`, AWS keys, `shortenerenv/`, `dist/`, `build/`, or `*.zip`.

## Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python3 -m ruff check .
python3 -m ruff format .
python3 -m pytest
python3 local_server.py
```

`make install`, `make lint`, `make format`, `make test`, and `make run` call the same tools. CI (`.github/workflows/ci.yml`) runs Ruff and pytest on Python 3.12.

## Gotchas

- The 2017 handlers used Python 2 syntax (`except Exception, exc`). They do not run on a current Lambda runtime. Stay on Python 3.
- `normalize_url` keeps `http` and `https` and prefixes `https://` when the scheme is missing. Do not strip the scheme again. `redirect_location` still prefixes `http://` for a schemeless stored value so codes written in 2017 resolve.
- A search outage used to replace the redirect with an exception. Logging has to stay best-effort.
- A missing DynamoDB item used to raise `KeyError` on `item["Item"]` after the search write. Return `{"error": "short url not found"}` and do not index that request.
- `config.yaml` used to contain blank `aws_access_key_id` / `aws_secret_access_key` fields from the python-lambda template. Leave credentials out of the repo. The IAM role or the default credential chain supplies them.
- The 2017 redirect module hardcoded an Amazon Elasticsearch hostname. The endpoint now comes only from `ELASTICSEARCH_URL`.
- Those hostnames, the virtualenv, and the deploy zips are still inside old commits. Do not copy them back into the tree. History was left in place because it held no live credentials.
- The indexed document is the raw invoke event, which can include request headers once API Gateway is wired up. That matches the 2017 behavior.
- OpenSearch Serverless (`aoss`) is not signed. This client signs Amazon OpenSearch Service domains with service `es`.
- `GET /` and `GET /health` on the local server are status checks, so they are not short codes.
- Packaging the redirect function for real logging means installing `requirements.txt` into the zip and deleting the bundled `boto3`, `botocore`, and `s3transfer` so Lambda's copies win. The README has the commands.
- `boto3.client("dynamodb")` is only reached when a caller passes no client. Tests that forget to inject one will use whatever AWS credentials the environment has.
