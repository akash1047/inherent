# inh-public-api-svc

Customer-facing API and MCP (Model Context Protocol) server for the Inherent Knowledge Base.

## Overview

This service provides:
- **REST API** for programmatic access to the knowledge base
- **MCP Server** for AI agent integration (Claude, etc.)

Both services authenticate using API keys that are validated against PostgreSQL.

### Access URLs

| Environment | URL |
|-------------|-----|
| Production  | `https://api.inherent.systems` |
| Development | `https://dev-api.inherent.systems` |
| Local       | `http://localhost:8000` |

The service is exposed on its own subdomain via Nginx reverse proxy. Requests to `dev-api.inherent.systems` (or `api.inherent.systems` in production) are forwarded directly to this service -- no path prefix stripping required.

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Health check (liveness) |
| `/health/ready` | GET | None | Readiness probe (DB + Weaviate) |
| `/v1/search` | POST | `search` | Semantic search across documents |
| `/v1/documents` | GET | `read` | List documents in workspace |
| `/v1/documents/{id}` | GET | `read` | Get document details |
| `/v1/documents` | POST | `write` | Upload a document for ingestion |
| `/v1/chunks/{doc_id}` | GET | `read` | Get document chunks |
| `/v1/chunks/{doc_id}/context` | GET | `read` | Get full document context |

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_documents` | Semantic search with API key auth |
| `get_document_context` | Retrieve full document content |
| `list_documents` | List workspace documents |

## Authentication

All endpoints require an API key. Provide it via:
- `X-API-Key` header (preferred)
- `Authorization: Bearer <key>` header

## Quick Start

### Local Development

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Set environment variables
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/knowledge_base"
export WEAVIATE_URL="http://localhost:8080"
export SERVICE_MODE="api"

# Run the service
python -m src.main
```

### Docker

```bash
docker build -t inh-public-api-svc .
docker run -p 8000:8080 \
  -e DATABASE_URL="..." \
  -e WEAVIATE_URL="..." \
  inh-public-api-svc
```

### API Example

```bash
# Search documents (dev environment)
curl -X POST https://dev-api.inherent.systems/v1/search \
  -H "X-API-Key: ink_your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"query": "how to configure settings", "limit": 5}'

# List documents
curl https://dev-api.inherent.systems/v1/documents \
  -H "X-API-Key: ink_your_api_key"

# Upload a document (requires 'write' permission)
curl -X POST https://dev-api.inherent.systems/v1/documents \
  -H "X-API-Key: ink_your_api_key" \
  -F "file=@./my-document.pdf"

# Get document context
curl https://dev-api.inherent.systems/v1/chunks/doc_123/context \
  -H "X-API-Key: ink_your_api_key"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | required | PostgreSQL connection string |
| `WEAVIATE_URL` | `http://localhost:8080` | Weaviate instance URL |
| `SERVICE_MODE` | `both` | `api`, `mcp`, or `both` |
| `API_PORT` | `8000` | REST API port |
| `MCP_PORT` | `8001` | MCP server port |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ENVIRONMENT` | `development` | Environment name |
| `AWS_S3_ENDPOINT` | — | S3-compatible endpoint URL |
| `AWS_ACCESS_KEY_ID` | — | S3 access key |
| `AWS_SECRET_ACCESS_KEY` | — | S3 secret key |
| `AWS_S3_BUCKET` | `inherent-documents` | S3 bucket for document storage |
| `REDIS_URL` | `redis://localhost:6379` | Redis URL for MQ publishing |

## Testing

```bash
# Run all tests (unit + e2e)
uv run pytest tests/unit/ tests/e2e/ tests/test_api_key_auth.py

# Run with coverage
uv run pytest --cov=src tests/unit/ tests/e2e/

# Run only unit tests
uv run pytest tests/unit/

# Run only E2E tests
uv run pytest tests/e2e/

# Run linting + formatting + type check
uv run ruff check src/ tests/
uv run black --check src/ tests/
uv run mypy src/
```

### Test Structure

```
tests/
├── unit/                        # Unit tests (mocked services)
│   ├── test_auth_service.py     # Auth service & dependencies
│   ├── test_documents_endpoint.py  # Document list/detail
│   ├── test_search_endpoint.py  # Search endpoint
│   ├── test_chunks_endpoint.py  # Chunks & context
│   ├── test_upload_document.py  # Document upload
│   ├── test_storage_service.py  # S3 storage service
│   ├── test_mq_service.py       # Redis MQ service
│   ├── test_exceptions.py       # Exception hierarchy
│   ├── test_problem_details.py  # RFC 7807 responses
│   ├── test_rate_limiter.py     # Rate limiting algorithm
│   └── test_validators.py       # Input validation
├── e2e/                         # End-to-end API flow tests
│   └── test_api_flows.py        # Full request→response chains
├── integration/                 # Integration tests (needs DB)
│   ├── test_health_endpoints.py
│   └── test_rate_limiting.py
└── test_api_key_auth.py         # API key model tests
```

## Architecture

```
┌─────────────────┐     ┌──────────────────────────┐
│   AI Agent /    │────>│    inh-public-api-svc    │
│   SDK / curl    │     │  - REST API :8000        │
└─────────────────┘     │  - MCP Server :8001      │
                        └──────────────────────────┘
                               │          │
                    ┌──────────┴──┐   ┌───┴──────────┐
                    ▼             ▼   ▼              ▼
             ┌──────────┐  ┌─────────┐  ┌──────┐  ┌───────┐
             │PostgreSQL │  │Weaviate │  │  S3  │  │ Redis │
             │(Read-Only)│  │(R/O)    │  │Upload│  │  MQ   │
             └──────────┘  └─────────┘  └──────┘  └───────┘
                                                       │
                                                       ▼
                                              ┌──────────────┐
                                              │ingestion-svc │
                                              │(async process)│
                                              └──────────────┘
```

### Upload Flow

```
Client ──POST /api/v1/documents──> public-api-svc
  1. Validate file (type, size, auth)
  2. Upload to S3 (inherent-documents bucket)
  3. Publish to Redis Stream (core.document.uploaded.v1)
  4. Return 201 {status: "pending"}
                                        ↓
                              ingestion-svc picks up MQ message
                              → parse → chunk → embed → index
```

## API Key Management

API keys are created and managed via the `inh-intg-svc` service:

```bash
# Create an API key (via intg-svc)
curl -X POST https://api.inherent.systems/api/v1/api-keys \
  -H "X-User-Email: user@example.com" \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "ws_123", "name": "My API Key"}'
```

The key is stored in PostgreSQL and validated locally by this service.
