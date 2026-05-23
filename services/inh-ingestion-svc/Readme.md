# Inherent Ingestion Service

Document ingestion pipeline that processes files (PDF, DOCX, HTML, JSON, TXT, CSV), chunks them, generates embeddings, and stores the results in PostgreSQL (truth) and Weaviate (memory). Orchestrated by [Temporal](https://temporal.io/) for durability and fault tolerance.

## Architecture

```
HTTP / Pub/Sub
      │
      ▼
┌─────────────┐     ┌──────────────────┐
│  Trigger     │────▶│  Temporal Server  │
│  (API/MQ)    │     │  localhost:7233   │
└─────────────┘     └────────┬─────────┘
                             │ task queue
                             ▼
                    ┌─────────────────┐
                    │  Worker          │
                    │  (activities)    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         PostgreSQL      Weaviate       GCS/Local
         (truth)         (memory)       (files)
```

### Ingestion Pipeline (V1 — MQ-driven)

1. **ensure_tenant_ready** — create workspace + tenant in PG & Weaviate
2. **fetch_document** — validate file exists in storage
3. **extract_text** — parse file (PDF/DOCX/HTML/etc.), write text to staging
4. **chunk_text** — split into chunks (sentences/paragraphs/tokens strategy)
5. **store_postgresql** — insert document metadata + chunks into `document_chunks`
6. **store_weaviate** — upsert embeddings
7. **update_workspace_stats** — increment counters
8. **cleanup_staging** — remove temporary data (runs in `finally`)

Large payloads (extracted text, chunk lists) are staged in the `ingestion_staging` PostgreSQL table to stay under Temporal's 4 MB gRPC limit. Only IDs and counts flow through workflow history.

## Service Modes

Configure via `SERVICE_MODE` environment variable:

| Mode | Description | Dependencies |
|---|---|---|
| `pubsub` (default) | Pub/Sub listener, processes synchronously (no Temporal) | GCP Pub/Sub |
| `mcp` | MCP server only for AI workflow integration | — |
| `both` | Pub/Sub + MCP concurrently | GCP Pub/Sub |
| `temporal_worker` | Temporal worker only (processes workflows from queue) | Temporal server |
| `temporal_trigger` | Pub/Sub listener that starts Temporal workflows | GCP Pub/Sub, Temporal server |
| `temporal_all` | Worker + trigger in one process (VM deployment) | GCP Pub/Sub, Temporal server |
| `standalone` | **HTTP API + Temporal worker — no Pub/Sub needed** | Temporal server |

## Quick Start (Standalone Mode)

The fastest way to run locally. Requires only PostgreSQL, Weaviate, and Temporal — no GCP infrastructure.

### Prerequisites

```bash
# 1. PostgreSQL + Weaviate (via Docker)
make docker-up   # from repo root

# 2. Temporal dev server
temporal server start-dev
# → Server: localhost:7233, UI: http://localhost:8233
```

### Run

```bash
cd services/inh-ingestion-svc

# Install dependencies
uv sync

# Start the service
SERVICE_MODE=standalone \
INGESTION_API_KEY=your-secret-key \
TEMPORAL_HOST=localhost:7233 \
uv run python -m src.main
```

The service starts on `http://localhost:8000` with Swagger docs at `/docs`.

### API Endpoints

All `/ingest` endpoints require the `X-API-Key` header.

#### Health Check

```bash
curl http://localhost:8000/health
```

```json
{"status": "healthy", "temporal_worker": true, "version": "0.3.0"}
```

#### Trigger Ingestion

```bash
curl -X POST http://localhost:8000/ingest \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "doc_001",
    "workspace_id": "ws_001",
    "user_id": "user_001",
    "filename": "report.pdf",
    "original_filename": "quarterly-report.pdf",
    "content_type": "application/pdf",
    "size_bytes": 102400,
    "storage_backend": "local",
    "storage_path": "workspaces/ws_001/report.pdf"
  }'
```

Returns **202 Accepted**:

```json
{"workflow_id": "ingest-doc_001", "document_id": "doc_001", "status": "started"}
```

Add `?wait=true` to block until completion and receive the full result as **200 OK**.

#### Check Status

```bash
curl http://localhost:8000/ingest/doc_001/status \
  -H "X-API-Key: your-secret-key"
```

```json
{
  "workflow_id": "ingest-doc_001",
  "document_id": "doc_001",
  "step": "chunking_text",
  "progress": 55,
  "chunks_created": 12,
  "skipped_unchanged": false
}
```

## Configuration

Copy `.env.example` to `.env` and configure:

### Required (all modes)

| Variable | Description | Example |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/knowledge_base` |
| `WEAVIATE_URL` | Weaviate endpoint | `http://localhost:8080` |
| `GCP_PROJECT_ID` | GCP project (can be empty for local) | `my-project` |
| `STORAGE_BUCKET` | GCS bucket (can be empty for local) | `my-bucket` |
| `PUBSUB_SUBSCRIPTION` | Pub/Sub subscription path (required by settings, can be dummy for standalone) | `projects/p/subscriptions/s` |

### Standalone Mode

| Variable | Description | Default |
|---|---|---|
| `SERVICE_MODE` | Set to `standalone` | `pubsub` |
| `INGESTION_API_KEY` | **Required.** Secret key for `X-API-Key` auth | — |
| `API_HOST` | HTTP server bind address | `0.0.0.0` |
| `API_PORT` | HTTP server port | `8000` |

### Temporal

| Variable | Description | Default |
|---|---|---|
| `TEMPORAL_HOST` | Temporal server address | `localhost:7233` |
| `TEMPORAL_NAMESPACE` | Temporal namespace | `default` |
| `TEMPORAL_TASK_QUEUE` | Task queue name | `document-ingestion` |

### Processing

| Variable | Description | Default |
|---|---|---|
| `CHUNKING_STRATEGY` | `sentences`, `paragraphs`, or `tokens` | `sentences` |
| `MAX_CHUNK_SIZE` | Max characters per chunk | `1000` |
| `CHUNK_OVERLAP` | Overlap characters between chunks | `200` |
| `EMBEDDING_ENABLED` | Generate embeddings | `true` |
| `EMBEDDING_MODEL` | Sentence-transformer model | `all-MiniLM-L6-v2` |
| `STORAGE_BACKEND` | `local`, `gcs`, or `s3` | `gcs` |

## Project Structure

```
src/
├── main.py                  # Entry point, mode dispatcher
├── config/
│   └── settings.py          # Pydantic settings (env vars)
├── api/                     # Standalone HTTP API
│   ├── app.py               # FastAPI app, routes, request/response models
│   └── auth.py              # X-API-Key auth (hmac.compare_digest)
├── temporal/
│   ├── worker.py            # Worker lifecycle management
│   ├── trigger.py           # Pub/Sub → Temporal bridge
│   ├── models.py            # Workflow I/O dataclasses
│   ├── workflows/
│   │   └── document_ingestion.py      # MQ-driven ingestion workflow
│   └── activities/
│       ├── tenant.py        # Tenant/workspace setup
│       ├── fetch.py         # Storage validation
│       ├── extract.py       # Text extraction (PDF, DOCX, HTML, etc.)
│       ├── chunk.py         # Text chunking (3 strategies)
│       ├── store.py         # PG/Weaviate storage
│       └── cleanup.py       # Staging cleanup
├── services/
│   ├── database.py          # PostgreSQL (SQLAlchemy, multi-tenant)
│   ├── weaviate.py          # Weaviate (multi-tenant collections)
│   ├── processor.py         # Synchronous ingestion (non-Temporal)
│   ├── mq/                  # Message queue (Redis Streams)
│   ├── staging.py           # Temporal staging table for large payloads
│   ├── storage.py           # S3/local file access
│   └── tenant_manager.py    # Multi-tenancy orchestration
├── connectors/              # File source adapters
├── models/                  # Pydantic data models
└── utils/                   # Logging, helpers
```

## Database Ownership

| Store | Owner | Other services |
|---|---|---|
| **PostgreSQL** | Ingestion service (read/write) | intg-svc (read-only) |
| **Weaviate** | Ingestion service (read/write) | intg-svc (read-only) |
| **MongoDB** | intg-svc (read/write) | Ingestion service **never** accesses |

## Testing

```bash
# Run all ingestion tests
uv run pytest

# Run only API tests (no database required)
uv run pytest tests/test_api.py -v

# With coverage
uv run pytest --cov=src --cov-report=term-missing
```

## Migrations

SQL migrations live in `scripts/migrations/`:

| File | Description |
|---|---|
| `000_initial_schema.sql` | Base tables |
| `001_consolidated_schema.sql` | Schema consolidation |
| `002_multi_tenancy.sql` | Tenants + workspace metadata |
| `003_user_scoped_api_keys.sql` | API key management |
| `005_ingestion_staging.sql` | Temporal staging table |
| `007_drop_versioning.sql` | Removed versioning tables |
