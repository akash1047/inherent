# Inherent

Document ingestion and retrieval backend for building a RAG knowledge base.

This repository turns raw documents into searchable knowledge.

Add files such as PDFs, DOCX, HTML, JSON, text, or CSV. The system extracts text, chunks it, generates embeddings, stores the results in PostgreSQL and Weaviate, and exposes an API for search and retrieval.

In practical terms, this is the backend layer of a RAG system: ingestion, indexing, storage, and retrieval.

## About

Inherent is for teams that want to build search and question-answering workflows on top of their own documents without building the backend stack from scratch.

It gives you:

- a document ingestion pipeline
- chunking and embedding generation
- persistent storage for documents and chunks
- vector-backed search over indexed content
- an API layer for retrieving relevant results

## Why Use It

- Bring your own documents: ingest PDFs, DOCX, HTML, JSON, text, and CSV.
- Run locally: the repo ships with a Compose stack for the required databases and supporting services.
- Separate ingestion from retrieval: one service writes and indexes data, another serves search requests.
- Build on standard components: FastAPI, PostgreSQL, Weaviate, Temporal, Redis/Valkey, and S3-compatible storage.

## Key Features

- Multi-format ingestion for PDFs, DOCX, HTML, JSON, TXT, and CSV
- Chunking and embedding generation for semantic retrieval
- PostgreSQL as structured storage for documents and chunks
- Weaviate as vector index for similarity search
- REST API for search, document listing, chunk access, and context retrieval
- Local-first developer setup with Docker Compose

## What's In The Repo

- an ingestion service that processes and indexes documents
- a public API service that searches and returns document content
- a Docker Compose stack for running the databases and supporting services locally
- tests and service-level Python projects for development

## How It Works

The repository is split into two main services:

- `inh-ingestion-svc` owns document processing. It consumes upload events from Redis/Valkey, runs Temporal workflows, extracts and chunks content, generates embeddings through Hugging Face Text Embeddings Inference, and writes to PostgreSQL and Weaviate.
- `inh-public-api-svc` provides a customer-facing REST API over indexed content. It reads from PostgreSQL and Weaviate, can publish upload events for ingestion, and also supports an MCP server when launched in `mcp` mode.

Local development uses Docker Compose for the supporting infrastructure:

- PostgreSQL
- MongoDB
- Weaviate
- Valkey
- S3-compatible object storage via `s3rver`
- Temporal and Temporal UI
- Hugging Face Text Embeddings Inference

## System Architecture

```text
                 documents
                     |
                     v
          +------------------------+
          |  inh-ingestion-svc     |
          |  extract / chunk /     |
          |  embed / index         |
          +-----------+------------+
                      |
        +-------------+-------------+
        |                           |
        v                           v
  +-------------+             +-------------+
  | PostgreSQL  |             |  Weaviate   |
  | metadata    |             | vectors     |
  | chunks      |             | retrieval   |
  +------+------+             +------+------+
         \                           /
          \                         /
           v                       v
             +-------------------+
             | inh-public-api-svc|
             | search / retrieve |
             +---------+---------+
                       |
                       v
                    clients
```

## Typical Flow

1. A document is uploaded or queued for ingestion.
2. The ingestion service extracts text and splits it into chunks.
3. Embeddings are generated for those chunks.
4. Metadata and chunks are stored in PostgreSQL and Weaviate.
5. The public API searches the indexed content and returns relevant passages.

## First API Call

Once the stack is running, you can verify the public API is up:

```bash
curl http://localhost:18000/health
```

You can also verify the ingestion API:

```bash
curl http://localhost:18002/health
```

To trigger ingestion manually in a local setup:

```bash
curl -X POST http://localhost:18002/ingest \
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

## Prerequisites

- Docker and Docker Compose
- Python 3.11+
- `uv`

## Quickstart

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Build and start the local stack:

```bash
docker compose up --build
```

3. Wait for the services to become healthy. The embeddings container can take longer than the rest on first boot.

After the stack is up:

- send documents into the ingestion service
- let the ingestion pipeline extract, chunk, and embed them
- query the public API to search across the indexed content

## Local Endpoints

- Public API: `http://localhost:18000`
- Public API docs: `http://localhost:18000/docs`
- Ingestion API: `http://localhost:18002`
- Ingestion health: `http://localhost:18002/health`
- Temporal UI: `http://localhost:18233`
- Weaviate: `http://localhost:18080`
- S3-compatible storage: `http://localhost:19000`
- PostgreSQL: `localhost:15432`
- MongoDB: `localhost:27018`
- Valkey: `localhost:16379`

## Repository Layout

### `services/inh-ingestion-svc`

- Runs in `worker` mode by default in Compose.
- Starts a Temporal worker, subscribes to MQ events, and exposes an HTTP API when `INGESTION_API_KEY` is set.
- Owns writes to PostgreSQL and Weaviate.

See [services/inh-ingestion-svc/Readme.md](services/inh-ingestion-svc/Readme.md) for service-specific commands and API details.

### `services/inh-public-api-svc`

- Runs in `both` mode in Compose, which currently serves the REST API path.
- Supports standalone `api`, `mcp`, and `both` modes from the Python entrypoint.
- Reads indexed data from PostgreSQL and Weaviate and can enqueue document upload notifications for ingestion.

See [services/inh-public-api-svc/Readme.md](services/inh-public-api-svc/Readme.md) for service-specific commands and endpoint details.

## Development

Each service is maintained as its own Python project. Install and run checks per service:

```bash
cd services/inh-ingestion-svc
uv sync --extra dev --group dev
uv run ruff check src tests
uv run black --check src tests
uv run pytest
```

```bash
cd services/inh-public-api-svc
uv sync --extra dev --group dev
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
uv run bandit -c pyproject.toml -r src
uv run pytest
```

Repository-wide contribution guidance lives in [CONTRIBUTING.md](CONTRIBUTING.md).

## Security and Support

- Security reports: [SECURITY.md](SECURITY.md)
- Usage questions and support routes: [SUPPORT.md](SUPPORT.md)

## License

[MIT](LICENSE)
