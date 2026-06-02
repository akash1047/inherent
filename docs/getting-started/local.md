# Getting Started Locally

Use this guide to start the full Inherent stack, upload a sample document, wait
for ingestion, and run your first search.

## What You Will Run

Local development uses Docker Compose for the backing services and the two
Inherent services:

- `inh-public-api-svc` on `http://localhost:18000`
- `inh-ingestion-svc` on `http://localhost:18002`
- PostgreSQL, MongoDB, Weaviate, Valkey, s3rver, Temporal, and the embedding
  sidecar

The Makefile wraps the common commands so you do not need to memorize the
underlying `docker compose` and `uv` calls.

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- `uv`
- `curl`
- `jq` for the examples that parse JSON responses

## 1. Prepare Your Environment

From the repository root:

```bash
make setup
```

This creates `.env` from `.env.example` when needed and installs the dev
dependencies for both Python services.

Validate the environment:

```bash
make validate
```

If you are using Docker Compose, warnings about hostnames such as `postgres`,
`weaviate`, `valkey`, `s3rver`, or `text-embeddings-inference` are expected.
Those names resolve inside the Compose network. Use the published `localhost`
ports only when running an individual service directly on your host.

## 2. Start the Stack

Start everything in the background and seed a local public API key:

```bash
make dev
```

The first run can take several minutes because Docker images are built and the
embedding sidecar downloads its model.

The seeded local credentials are:

```bash
export API_BASE="http://localhost:18000"
export INGEST_BASE="http://localhost:18002"
export API_KEY="ink_dev_local_key_001"
export WORKSPACE_ID="ws_local_001"
```

Check service health:

```bash
make health
```

For a deeper readiness check:

```bash
curl -s "$API_BASE/health/ready" | jq .
```

## 3. Upload a Sample Document

Upload the committed sample text file through the public API:

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.txt;type=text/plain" \
  | tee /tmp/inherent-upload.json \
  | jq .
```

Save the document ID:

```bash
export DOC_ID="$(jq -r .document_id /tmp/inherent-upload.json)"
```

The upload response should show `status: "pending"`. Ingestion runs
asynchronously after the file is stored and an upload event is published.

## 4. Wait for Ingestion

Poll the document until its status becomes `processed`:

```bash
curl -s "$API_BASE/v1/documents/$DOC_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

If the document stays pending, inspect the ingestion logs:

```bash
make logs SVC=inh-ingestion-svc
```

You can also inspect the public API logs:

```bash
make logs SVC=inh-public-api-svc
```

## 5. Search Your Indexed Document

After the document is processed, run a search:

```bash
curl -s -X POST "$API_BASE/v1/search" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "what retrieval modes does Inherent support",
    "limit": 5
  }' \
  | jq .
```

Search with surrounding context:

```bash
curl -s -X POST "$API_BASE/v1/search" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "supported file formats",
    "limit": 3,
    "include_context": true,
    "context_window": 2
  }' \
  | jq .
```

Fetch the full reconstructed document context:

```bash
curl -s "$API_BASE/v1/chunks/$DOC_ID/context" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

## Common Commands

| Command | Purpose |
| --- | --- |
| `make help` | List available Makefile targets. |
| `make dev` | Start the stack in the background and seed the local API key. |
| `make up` | Start the stack in the foreground. |
| `make health` | Check public API and ingestion API health. |
| `make logs` | Follow all Compose logs. |
| `make logs SVC=inh-public-api-svc` | Follow one service's logs. |
| `make ps` | Show Compose service status. |
| `make down` | Stop the stack. |
| `make clean` | Stop the stack and remove local Compose volumes. |
| `make check` | Run validation, lint, formatting, typing, security checks, and tests. |

## Troubleshooting

### `make validate` prints Compose hostname warnings

This is expected when `.env` mirrors the Compose network. The warnings matter
only when you run services directly on your host instead of through Compose.

### The first startup is slow

The embedding sidecar downloads the configured model on first boot. Watch logs:

```bash
make logs SVC=text-embeddings-inference
```

### Upload succeeds, but search returns no results

Confirm the document reached `processed` status:

```bash
curl -s "$API_BASE/v1/documents/$DOC_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

Then check the ingestion service logs:

```bash
make logs SVC=inh-ingestion-svc
```

### You want a clean local database

Remove Compose volumes and start again:

```bash
make clean
make dev
```

## Next Steps

- Use [docs/examples/README.md](../examples/README.md) for endpoint-by-endpoint
  request examples.
- Open public API docs at `http://localhost:18000/docs`.
- Open Temporal UI at `http://localhost:18233`.
