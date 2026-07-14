# REST API reference

Base URL: `http://localhost:18000` on the local compose stack. All
application routes live under `/v1`. Swagger UI (`/docs`) and ReDoc
(`/redoc`) are exposed in development mode only.

Runnable curl examples for every endpoint: [API examples](../examples/README.md).

## Authentication

Send an API key on every `/v1` request, either header works:

```bash
curl -H "X-API-Key: <key>" http://localhost:18000/v1/documents
curl -H "Authorization: Bearer <key>" http://localhost:18000/v1/documents
```

- Missing/invalid/expired key → `401` (`WWW-Authenticate: ApiKey`).
- Missing permission → `403`. Errors return RFC 7807 problem-details JSON.
- A key carries a subset of three permissions: `read`, `search`, `write`
  (default `read, search`). Membership is exact — `write` does NOT imply
  `read` or `search`.

## Workspace scoping

Select a workspace with the `X-Workspace-Id` header.

- **Workspace-scoped key**: bound to its workspace; a mismatching
  `X-Workspace-Id` → `403`.
- **User-scoped key**: `X-Workspace-Id` must name a workspace the user owns
  (else `403`). Without the header, read/search fan out across all owned
  workspaces; write endpoints require an unambiguous workspace (`400` when
  the user owns zero or several).
- Cross-workspace documents read as `404`, not `403`.

## Endpoints

### Health & observability (no auth)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health`, `/health/live` | Liveness — returns immediately |
| GET | `/health/ready` | Readiness — checks PostgreSQL + Weaviate; `503` when unhealthy, `degraded` stays `200` |
| GET | `/metrics` | Prometheus metrics (when `METRICS_ENABLED=true`, default) |

### Search & verification

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| POST | `/v1/search` | `search` | Semantic / hybrid / keyword search. Request: `query` (1–1000 chars), `limit` (1–100, default 10), `min_score`, `document_ids[]`, `include_context`, `context_window` (0–5), `search_mode` (`semantic`/`hybrid`/`keyword`), `alpha` (0–1). Response: `results[]` (score provenance, `citation`, `is_stale`, `content_risk`), `quality_verdict`, `performed_fallback`, `event_id` (for eval feedback) |
| POST | `/v1/verify-claim` | `read` | Offline lexical claim-vs-evidence check. Request: `claim` (1–2000 chars), `evidence[]`. Response: `support_level` (`strong`/`weak`/`none`), `score`, `reason` |

### Documents

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| POST | `/v1/documents` | `write` | Upload (multipart `file`) for async ingestion. `201` with `document_id`, `status: "pending"`. Workspace required. Identical content dedupes to the existing document |
| GET | `/v1/documents` | `read` | List documents. Query: `page`, `page_size` (1–100, default 20) |
| GET | `/v1/documents/{id}` | `read` | Document metadata (`status`, `chunk_count`, `mime_type`, timestamps). `404` if not found |
| DELETE | `/v1/documents/{id}` | `write` | Delete document + vectors + chunks + stored bytes. `204`; `404` if already gone; `503` on vector-store outage (document left intact, retry safe) |
| GET | `/v1/documents/{id}/lineage` | `read` | Provenance + freshness: `source_uri`, `content_hash`, `ingested_at`, `is_stale`. Optional `chunk_id` query param |
| POST | `/v1/documents/{id}/refresh` | `write` + `read` | Re-ingest an uploaded document to clear staleness. `404` if missing; `503` on DB/MQ failure (document marked `failed`, never stranded `pending`) |

### Chunks

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/v1/chunks/{document_id}` | `read` | All chunks (`content`, `chunk_index`, `token_count`, `metadata`) |
| GET | `/v1/chunks/{document_id}/context` | `read` | Document metadata + all chunks + combined `full_text` |
| GET | `/v1/chunks/{document_id}/{chunk_id}` | `read` | Single chunk. Cross-tenant chunk reads as `404` |

### Evals (traffic-mined retrieval quality)

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| POST | `/v1/evals/feedback` | `search` | Report a verdict (`answered`/`partial`/`not_relevant`) on a search `event_id`; positive verdicts auto-promote the query to a labeled eval case |
| GET | `/v1/evals/scorecard` | `search` | Workspace retrieval health: `answer_rate`, `verdict_distribution`, `corpus_gaps`, `eval_case_count`, `low_confidence`, `last_run` |
| GET | `/v1/evals/cases` | `search` | Page labeled cases (`limit` 1–200, `offset`) |
| PATCH | `/v1/evals/cases/{case_id}` | `write` | Enable/disable a case (`{"active": bool}`) |
| POST | `/v1/evals/runs` | `write` | Start a keyword-vs-semantic-vs-hybrid comparison run. `202` with `run_id`; `409` when no active cases |
| GET | `/v1/evals/runs/{run_id}` | `search` | Run report: per-mode recall@k / MRR / nDCG aggregates + per-case metrics |
| DELETE | `/v1/evals/events` | `write` | Purge the workspace's captured search events |

## Rate limiting

Per-key limits (default 100 requests / 60 s window; key-specific overrides
supported). Unauthenticated or invalid-key traffic is limited per client IP
(`RATE_LIMIT_UNAUTHENTICATED`, default 30). See the
[configuration reference](configuration.md) for the toggles.
