# inh-ingestion-svc

Document ingestion service for the Inherent knowledge base OSS core.

This service processes uploaded documents, extracts text, chunks content, generates embeddings, and stores results in PostgreSQL and Weaviate. It is also responsible for consuming document upload events and orchestrating ingestion workflows through Temporal.

## Service Modes

Configure `SERVICE_MODE` with one of these values:

| Mode | Description |
| --- | --- |
| `worker` | Recommended default. Runs the Temporal worker, MQ subscriptions, metrics server, and HTTP API when `INGESTION_API_KEY` is set. |
| `standalone` | Runs the HTTP API for manual ingestion triggers. |

Legacy mode names such as `pubsub`, `temporal_worker`, `temporal_trigger`, and `temporal_all` are mapped internally to `worker` for backward compatibility, but new documentation and local setup should use `worker`.

## Local Development

### Dependencies

- Python 3.11+
- `uv`
- PostgreSQL
- Weaviate
- Valkey
- MongoDB
- Temporal
- optional S3-compatible storage when using `STORAGE_BACKEND=s3`

The root `docker-compose.yml` starts the full local dependency stack.

### Install

```bash
uv sync --extra dev --group dev
```

### Run in Standalone Mode

```bash
SERVICE_MODE=standalone \
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/knowledge_base \
WEAVIATE_URL=http://localhost:18080 \
REDIS_URL=redis://localhost:16379 \
MONGODB_URI=mongodb://localhost:27018 \
TEMPORAL_ENABLED=true \
TEMPORAL_HOST=localhost:17233 \
INGESTION_API_KEY=dev-ingestion-key \
AWS_ACCESS_KEY_ID=S3RVER \
AWS_SECRET_ACCESS_KEY=S3RVER \
AWS_REGION=us-east-1 \
AWS_S3_ENDPOINT=http://localhost:19000 \
STORAGE_BACKEND=s3 \
STORAGE_BUCKET=inherent-documents \
EMBEDDING_SERVICE_URL=http://localhost:18088 \
uv run python -m src.main
```

### Run in Worker Mode

```bash
SERVICE_MODE=worker \
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/knowledge_base \
WEAVIATE_URL=http://localhost:18080 \
REDIS_URL=redis://localhost:16379 \
MONGODB_URI=mongodb://localhost:27018 \
TEMPORAL_ENABLED=true \
TEMPORAL_HOST=localhost:17233 \
INGESTION_API_KEY=dev-ingestion-key \
AWS_ACCESS_KEY_ID=S3RVER \
AWS_SECRET_ACCESS_KEY=S3RVER \
AWS_REGION=us-east-1 \
AWS_S3_ENDPOINT=http://localhost:19000 \
STORAGE_BACKEND=s3 \
STORAGE_BUCKET=inherent-documents \
EMBEDDING_SERVICE_URL=http://localhost:18088 \
uv run python -m src.main
```

## HTTP API

When `INGESTION_API_KEY` is set, the service exposes an HTTP API on `API_PORT` (default `8000`).

### Health Check

```bash
curl http://localhost:8000/health
```

### Trigger Ingestion

```bash
curl -X POST http://localhost:8000/ingest \
  -H "X-API-Key: dev-ingestion-key" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "doc_001",
    "workspace_id": "ws_001",
    "user_id": "user_001",
    "filename": "report.pdf",
    "original_filename": "report.pdf",
    "content_type": "application/pdf",
    "size_bytes": 102400,
    "storage_backend": "s3",
    "storage_path": "workspaces/ws_001/report.pdf"
  }'
```

## Validation Commands

```bash
uv run ruff check src tests
uv run black --check src tests
uv run pytest
```

## Project Layout

```text
src/
  api/         FastAPI app and auth helpers
  config/      Settings and environment handling
  connectors/  File source adapters
  models/      Pydantic models
  services/    Database, storage, embedding, MQ, and processing logic
  temporal/    Worker, trigger, and workflow-related components
  utils/       Logging and helpers
```
