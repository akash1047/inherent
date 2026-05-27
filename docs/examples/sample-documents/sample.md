# Inherent Knowledge Base — Sample Markdown Document

This Markdown file is used to test ingestion and retrieval of formatted content.

## Introduction

**Inherent** is a backend for turning company knowledge into something AI systems can query.
Upload documents → extract text → chunk → embed → search.

## Architecture

| Component       | Role                                      |
|-----------------|-------------------------------------------|
| inh-ingestion-svc | Processes uploads, runs Temporal workflows |
| inh-public-api-svc | Serves REST search and document endpoints  |
| PostgreSQL      | Structured metadata and chunk storage     |
| Weaviate        | Vector index for similarity search        |
| Valkey          | Message queue and rate-limit cache        |

## Quick Start

```bash
docker compose up --build
curl http://localhost:18000/health
```

## Retrieval Strategies

- `semantic` — pure vector similarity (default)
- `hybrid` — BM25 + vector, weighted by `alpha` (0.0–1.0)
- `keyword` — BM25 full-text only

## Notes

- Max upload size: 50 MB
- Authentication: `X-API-Key` header required for all `/v1/` routes
- Workspace scope: pass `X-Workspace-Id` header to restrict to one workspace
