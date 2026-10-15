# URL shortener

A small AWS URL shortener: one Lambda creates a short code for a destination URL and stores the pair in DynamoDB, and a second Lambda looks that code up and returns a redirect. Successful redirects can be written to OpenSearch so hits show up in an ELK-style index.

## Original context

Pranav Prem built this in November and December 2017 and the repository was not updated after that. The original functions were Python 2.7 Lambdas in `us-west-1`, packaged and deployed with [python-lambda](https://github.com/nficano/python-lambda). The creation function (`control_panel`) wrote rows to a DynamoDB table named `urls`. The redirect function (`link_redirect`) read that table and indexed each hit in Amazon Elasticsearch.

The checkout also contained the Python 2.7 virtualenv (`shortenerenv`) and timestamped Lambda zip files under `linkredirect/dist`. Those build artifacts are no longer in the tree. Older commits still have them.

## How it works

1. A caller sends a destination URL to `controlpanel.service.handler`. The function keeps an `http` or `https` scheme when one was provided, and assumes `https` when the scheme is missing. It stores the URL under a new `uuid4().hex` code (32 hex characters, the same kind of code the 2017 function generated).
2. A caller sends that code to `linkredirect.service.handler`. The function reads DynamoDB and returns `{"Location": "<url>"}` for API Gateway to turn into a 302.
3. When `ELASTICSEARCH_URL` is set, the redirect function indexes the invoke event in OpenSearch after a successful lookup. A logging failure is recorded in CloudWatch and the redirect still returns.

The DynamoDB table is named `urls` unless `DYNAMODB_TABLE` overrides it. The partition key is `shorturl` (string). The only other attribute is `url` (string).

The functions still speak the 2017 event shapes, which are plain dicts rather than Lambda proxy payloads:

```json
{ "url": "https://example.com/docs" }
```

```json
{ "params": { "path": { "shorturl": "0123456789abcdef0123456789abcdef" } } }
```

Sample files live at `controlpanel/event.json` and `linkredirect/event.json`.

Rows created by the 2017 function stored the host with the scheme removed, and the redirect always used `http://`. This version stores the full URL. A schemeless legacy row still redirects with `http://`, so old codes keep working.

## Run it today

Requires Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
python local_server.py
```

`local_server.py` listens on `http://127.0.0.1:8000` (override with `PORT`). It keeps the table in memory and does not call AWS.

```bash
curl -s -X POST http://127.0.0.1:8000/ \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/docs"}'

curl -s -D - -o /dev/null http://127.0.0.1:8000/<shorturl>
```

`POST /shorten` accepts the same JSON body. `GET /health` returns `{"status":"ok"}`.

Lint and format with Ruff:

```bash
ruff check .
ruff format .
```

`make test`, `make lint`, and `make run` wrap the same commands.

### Deploy the Lambdas

Create the DynamoDB table in the region you plan to use (the 2017 functions used `us-west-1`):

- Name: `urls` (or whatever you set as `DYNAMODB_TABLE`)
- Partition key: `shorturl` (String)

The control panel zip is only its handler. Lambda already provides boto3.

```bash
mkdir -p dist
zip -j dist/control_panel.zip controlpanel/service.py
aws lambda update-function-code \
  --function-name control_panel \
  --zip-file fileb://dist/control_panel.zip
```

The redirect function is the same shape when hit logging is off. To turn logging on, vendor `opensearch-py` into that zip and leave boto3 out so the runtime copy is used:

```bash
rm -rf build/linkredirect
python3 -m pip install -r requirements.txt -t build/linkredirect
rm -rf build/linkredirect/boto3 build/linkredirect/botocore \
  build/linkredirect/s3transfer build/linkredirect/*.dist-info
cp linkredirect/service.py build/linkredirect/
(cd build/linkredirect && zip -r ../../dist/link_redirect.zip .)
```

Point each function at handler `service.handler` and runtime `python3.12`. Allow `control_panel` `dynamodb:PutItem` and `link_redirect` `dynamodb:GetItem` on the table. Allow the redirect function `es:ESHttpPost` when it writes to OpenSearch. Set `DYNAMODB_TABLE`, and for hit logging set `ELASTICSEARCH_URL` (for example `https://search-example.us-west-1.es.amazonaws.com`) and optionally `ELASTICSEARCH_INDEX` (default `urls`).

Wire API Gateway with mapping templates that produce the event shapes above, and map the `Location` field onto a 302 response. `controlpanel/config.yaml` and `linkredirect/config.yaml` record the function name, region, and runtime. They are notes for that deploy. The old `lambda deploy` command from python-lambda is not part of this tree anymore.

AWS credentials come from the function's IAM role, or from the default credential chain locally. Access keys do not belong in the repo.

## Tech stack

| Piece | 2017 | Now |
| --- | --- | --- |
| Language | Python 2.7 | Python 3.12 |
| Compute | Two Lambda functions | Same two functions |
| Storage | DynamoDB table `urls` | Same table and key |
| Hit log | `elasticsearch` 5.4 against Amazon Elasticsearch | Optional `opensearch-py` 3.2, SigV4 on AWS hosts |
| AWS SDK | boto3 1.4.4, vendored in a committed virtualenv | boto3 1.43.114 locally; the Lambda runtime's boto3 when deployed |
| Packaging | python-lambda 2.2.0 | `zip` and the AWS CLI |
| Tests and CI | None | pytest and GitHub Actions |
| Lint | None | Ruff |

Direct dependencies are pinned in `requirements.txt` and `requirements-dev.txt`.

## Project structure

```
controlpanel/service.py    Create a short code (Lambda handler)
linkredirect/service.py    Resolve a code (Lambda handler)
local_server.py            In-memory HTTP stand-in for local use
tests/                     pytest suite
.github/workflows/ci.yml   Lint and test on Python 3.12
```

Each directory's `config.yaml` and `event.json` describe that function's deploy settings and a sample event.

The handlers return JSON documents. There is no HTML interface, so this repository has no screenshots.

## Configuration

| Variable | Default | Used by |
| --- | --- | --- |
| `DYNAMODB_TABLE` | `urls` | Both functions |
| `ELASTICSEARCH_URL` | unset (logging off) | Redirect |
| `ELASTICSEARCH_INDEX` | `urls` | Redirect |
| `AWS_REGION` | Parsed from `*.es.amazonaws.com` when it can be | Signing OpenSearch requests |
| `PORT` | `8000` | Local server only |

`.env.example` lists the same names. Copy it to `.env` for local notes. `.env` is gitignored.
