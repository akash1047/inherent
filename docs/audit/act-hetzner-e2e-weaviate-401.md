---
search:
  exclude: true
---

# Act Hetzner e2e failure — Weaviate 401 (stale public-api image)

**Date:** 2026-07-11  
**Workflow:** `.github/workflows/hetzner-e2e.yml`  
**Evidence:** Local `act` run (not committed; log was ephemeral on the operator machine). Symptoms excerpted below.

## Summary

Local `act` simulation of Hetzner e2e left infra green (TF local backend, apply, `/health`, SSH bootstrap, destroy) and turned red only on `pytest -m compose`. Root cause is **image/source skew**: release compose enables Weaviate API-key auth and injects `WEAVIATE_API_KEY`, but published `public-api-svc:latest` still builds an unauthenticated httpx client, so GraphQL calls return 401 and surface as public-api 500s. Git `main` already sends `Authorization: Bearer`; GHCR `latest` does not.

## What was run

- Tool: `act` with `workflow_dispatch` on `hetzner-e2e.yml`
- Secret: `HCLOUD_TOKEN` (present; gate step passed)
- Inputs: `inherent_version=latest`, `server_type=cpx22`
- Backend: CI override to **local** Terraform state (`infra/zzz_ci_backend_override.tf`) — not Object Storage
- VM stack: cloud-init pulls main `docker-compose.release.yml`, writes `/opt/inherent/.env`, `docker compose up -d`
- Default env includes `WEAVIATE_API_KEY=changeme` (`infra/server.tf`)

## Step matrix

| Step | Result |
|------|--------|
| Checkout / Require HCLOUD_TOKEN / SSH key / TF setup / uv | pass |
| Terraform init (local state) | pass |
| Terraform apply | pass |
| Wait public API healthy (`:18000/health`) | pass |
| Bootstrap dev workspace + API key (SSH) | pass |
| `pytest -m compose` (public-api) | **fail** (9/9 failed) |
| Dump Compose logs on failure | pass |
| Terraform destroy | pass |

## Root cause

1. **Release compose enables Weaviate API-key auth** — anonymous disabled; `AUTHENTICATION_APIKEY_*` from `WEAVIATE_API_KEY` (`docker-compose.release.yml:88-96`).
2. **Env key is set** — default TF env sets `WEAVIATE_API_KEY=changeme`; public-api service receives it (`infra/server.tf:17`, `docker-compose.release.yml:284`).
3. **Ingestion authenticates successfully** — uses `Auth.api_key(...)` under the same env (`services/inh-ingestion-svc/src/services/weaviate.py:85-93`). Uploads, MQ publish, and Weaviate writes proceed.
4. **Published `public-api-svc:latest` lacks Bearer** — image Created ~2026-07-04T03:25Z. Search client constructor is effectively `(database, weaviate_url)` only; httpx client has no `Authorization` header. Images publish only on `v*` tags or `workflow_dispatch` (`.github/workflows/publish.yml:18-22`), so `latest` lagged main.
5. **Git source on main already has Bearer** — `SearchService` takes `weaviate_api_key`, sets `Authorization: Bearer {api_key}`, and `get_search_service` passes `settings.weaviate_api_key` (`search.py:150-167`, `search.py:733-741`; #86-era).
6. **Result** — public-api GraphQL `POST /v1/graphql` → **401 Unauthorized** → public-api wraps as **500** on `/v1/search` → all search-related compose tests fail. `/health` does not exercise Weaviate auth, so health green is not sufficient.

## Evidence

Symptoms captured from a local `act` run (operator machine; not stored in this repo).

- Workflow path: health → bootstrap → compose tests (`.github/workflows/hetzner-e2e.yml`); local TF backend override used for that act run.
- VM boot: pulls release compose + `.env`, starts stack (`infra/cloud-init.yaml.tftpl:27-34`).
- Observed failures:
  - Search: HTTP `500` with detail  
    `HTTPStatusError: Client error '401 Unauthorized' for url 'http://weaviate:8080/v1/graphql'`
  - Container log: `inherent-oss-public-api` same 401 on GraphQL
  - Ingestion path live: document upload accepted, S3 put, MQ publish on `core.document.uploaded.v1` (ingestion not blocked by Weaviate auth the way public-api search is)
  - Health alone insufficient: `public API healthy on …` then compose still failed
  - Lifecycle residual: `assert 'processed' in {'pending', 'processing'}` (status never reaches `processed`)
  - Postgres residual: `relation "ingestion_events" does not exist`
  - TEI residual: ONNX download 404 warnings for `model.onnx` / `model.onnx_data` (fallback path continued)

## Non-causes

| Suspect | Why ruled out |
|---------|----------------|
| `act` runner / workflow wiring | All infra steps succeeded; only compose tests failed |
| Missing `HCLOUD_TOKEN` | Require-token step passed; apply created real Hetzner resources |
| Terraform S3 / Object Storage backend | Job overrides to local backend; init reported `backend "local"` |
| SSH / bootstrap failure | Bootstrap step succeeded; tests reached authenticated API calls |
| Missing `WEAVIATE_API_KEY` in env | Key set in default env; Weaviate and ingestion use it; failure is client omitting Bearer |
| Weaviate misconfig only | Same stack accepts authenticated ingestion; public-api GraphQL is the unauthenticated client |

## Secondary findings

Defer until after public-api image republish:

1. **`ingestion_events` relation missing** — Postgres `ERROR: relation "ingestion_events" does not exist` on lineage inserts during workflows.
2. **Status never `processed`** — `test_upload_status_lifecycle` saw only `pending` / `processing` (may couple to lineage/image skew; re-check after Bearer fix).
3. **TEI ONNX 404 warnings** — HF paths for `model.onnx` / `model.onnx_data` 404 then fallback; not the primary 401 root cause.

## Fix order

1. **Republish** `public-api-svc` from current `main` (tag/`workflow_dispatch` per `publish.yml`) so GHCR includes Bearer Weaviate auth.
2. **Smoke-grep** the new image for Bearer usage (e.g. strings/`Authorization` / `weaviate_api_key` in SearchService path) before re-running e2e.
3. **Re-run act** Hetzner e2e (`latest` or new tag) with the same local-backend workflow.
4. **Address residual** failures only if they remain after image skew is fixed (`ingestion_events` migration, status lifecycle, TEI ONNX noise).

## References (source of truth)

| Topic | Location |
|-------|----------|
| Local TF backend in CI | `.github/workflows/hetzner-e2e.yml:66-75` |
| Health / bootstrap / compose | `.github/workflows/hetzner-e2e.yml:94-120` |
| Cloud-init stack start | `infra/cloud-init.yaml.tftpl:27-34` |
| Default `WEAVIATE_API_KEY` | `infra/server.tf:8-37` |
| Weaviate API-key auth | `docker-compose.release.yml:88-96` |
| public-api image + env | `docker-compose.release.yml:269-284` |
| Bearer in source | `services/inh-public-api-svc/src/services/search.py:150-167`, `733-741` |
| Ingestion Auth.api_key | `services/inh-ingestion-svc/src/services/weaviate.py:85-93` |
| Publish triggers | `.github/workflows/publish.yml:18-22` |
