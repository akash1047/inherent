# Inherent OSS Core

This folder is the first simplified OSS cut of Inherent's core runtime.

It contains:

- `services/inh-ingestion-svc` - document ingestion, chunking, embedding, and indexing
- `services/inh-public-api-svc` - public REST API and MCP server
- `docker-compose.yml` - local infrastructure and service runner

It intentionally does not include the SaaS dashboard, admin app, billing cron, landing site, production infrastructure, deployment workflows, or private project planning files.

## Run Locally

From this folder:

```bash
cp .env.example .env
docker compose up --build
```

Useful local URLs:

- Public API: `http://localhost:18000`
- Public API health: `http://localhost:18000/health`
- Public API MCP: `http://localhost:18001`
- Ingestion API: `http://localhost:18002`
- Ingestion health: `http://localhost:18002/health`
- Temporal UI: `http://localhost:18233`
- Weaviate: `http://localhost:18080`
- S3-compatible storage: `http://localhost:19000`
- Postgres: `localhost:15432`
- MongoDB: `localhost:27018`
- Valkey: `localhost:16379`

## Notes

- The first compose run applies PostgreSQL migrations from `services/inh-ingestion-svc/scripts/migrations`.
- The embedding sidecar uses Hugging Face Text Embeddings Inference with `BAAI/bge-small-en-v1.5` by default.
- The public API is configured for local development and permissive CORS.
- This folder is meant to be easy to copy into a new public repository later.
