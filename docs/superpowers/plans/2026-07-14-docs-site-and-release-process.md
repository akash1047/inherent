# Documentation Site + Release Process Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish an MkDocs Material documentation site to GitHub Pages with new reference pages and on-site release notes, publish GitHub Releases for existing tags, and make changelog + docs updates a mandatory part of every change via CLAUDE.md and releasing.md.

**Architecture:** `mkdocs.yml` at repo root wraps the existing `docs/` tree (no file moves); root files (CHANGELOG, CONTRIBUTING, ...) render on-site through `pymdownx.snippets` stub pages so each has one source of truth. A `docs.yml` workflow builds with `--strict` on PRs and deploys to Pages on `main`. Three new hand-written reference pages close the consumer gap (REST API, MCP tools, configuration).

**Tech Stack:** MkDocs Material (pinned via `requirements-docs.txt`), GitHub Actions Pages deploy (`actions/deploy-pages`), `gh` CLI for releases.

**Spec:** `docs/superpowers/specs/2026-07-14-docs-site-design.md`

## Global Constraints

- Work on branch `docs/site-and-release-process` (already created, spec committed).
- `mkdocs build --strict` must pass at the end of every task from Task 1 on — a warning is a failure.
- Follow repo Writing Standards: concise, active voice, prescription-style docs for AI-agent readers.
- Document ONLY behavior that exists in this repository (rule in `docs/README.md`). The reference-page content in this plan was extracted from the code on 2026-07-14; if a statement conflicts with the code, the code wins — fix the content, don't copy the conflict.
- Do NOT rewrite historical CHANGELOG entries. Sole exception: converting relative Markdown links to absolute GitHub URLs (needed for on-site rendering and GH Releases; not a content change).
- Repo URLs: `https://github.com/inherent-prime/inherent`. Pages URL: `https://inherent-prime.github.io/inherent/`.
- Commit after every task with a `docs:`/`ci:`/`chore:` conventional message ending with the Claude co-author trailer.

---

### Task 1: MkDocs scaffold — config, landing page, stub pages, strict build green

**Files:**
- Create: `requirements-docs.txt`
- Create: `mkdocs.yml`
- Create: `docs/index.md`
- Create: `docs/release-notes.md`
- Create: `docs/community/contributing.md`, `docs/community/code-of-conduct.md`, `docs/community/security.md`, `docs/community/support.md`
- Create: `docs/reference/rest-api.md`, `docs/reference/mcp-tools.md`, `docs/reference/configuration.md` (placeholder one-liners so nav resolves; Tasks 2–4 fill them)
- Modify: `CHANGELOG.md` (link normalization only), any `docs/**/*.md` with links that fail strict build

**Interfaces:**
- Produces: a green `mkdocs build --strict` that Tasks 2–8 keep green; nav paths `reference/rest-api.md`, `reference/mcp-tools.md`, `reference/configuration.md` that Tasks 2–4 fill.

- [ ] **Step 1: Create `requirements-docs.txt`**

```text
mkdocs-material>=9.5,<10
```

- [ ] **Step 2: Install and verify**

Run: `python3 -m pip install -r requirements-docs.txt && mkdocs --version`
Expected: prints an mkdocs version (1.6+).

- [ ] **Step 3: Create `mkdocs.yml`**

```yaml
site_name: Inherent
site_description: >-
  Self-hostable, permission-aware agent memory substrate — ingestion,
  indexing, storage, and retrieval for private RAG.
site_url: https://inherent-prime.github.io/inherent/
repo_url: https://github.com/inherent-prime/inherent
repo_name: inherent-prime/inherent
edit_uri: edit/main/docs/
docs_dir: docs

theme:
  name: material
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: black
      toggle:
        icon: material/weather-night
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: black
      toggle:
        icon: material/weather-sunny
        name: Switch to light mode
  features:
    - navigation.tabs
    - navigation.top
    - navigation.footer
    - search.suggest
    - search.highlight
    - content.action.edit
    - content.code.copy

markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - toc:
      permalink: true
  - pymdownx.highlight
  - pymdownx.superfences
  - pymdownx.details
  - pymdownx.snippets:
      base_path: ["."]
      check_paths: true

plugins:
  - search

# Internal artifacts never published to the site.
# /README.md would collide with index.md (both map to site root).
exclude_docs: |
  /README.md
  superpowers/
  examples/__pycache__/

# Built (so in-repo links keep working) but intentionally not in the nav.
not_in_nav: |
  audit/
  maintainers/
  developer/

nav:
  - Home: index.md
  - Getting Started:
      - Local quickstart: getting-started/local.md
      - Production (Hetzner + Terraform): getting-started/production.md
      - Laptop VM test: getting-started/local-vm-test.md
  - Guides:
      - Production hardening: deploy/production.md
      - Testing: testing.md
      - Advanced indexes: advanced-indexes.md
  - Reference:
      - API examples: examples/README.md
      - REST API: reference/rest-api.md
      - MCP tools: reference/mcp-tools.md
      - Configuration: reference/configuration.md
  - Release Notes: release-notes.md
  - Architecture:
      - ADR index: adr/README.md
      - 0001 — Agent memory substrate: adr/0001-agent-memory-substrate.md
      - 0002 — Weaviate multi-tenancy scale: adr/0002-weaviate-multi-tenancy-scale.md
      - 0003 — Traffic-mined retrieval evals: adr/0003-traffic-mined-retrieval-evals.md
      - Threat model — RAG poisoning: threat-models/rag-poisoning-injection.md
  - Community:
      - Contributing: community/contributing.md
      - Code of Conduct: community/code-of-conduct.md
      - Security policy: community/security.md
      - Support: community/support.md
```

- [ ] **Step 4: Create `docs/index.md`** (landing page; content adapted from root README, plus the hub's fast routes so agents landing here can navigate)

```markdown
# Inherent

**Build your private company brain.**

Inherent is the backend for turning company knowledge into something AI
systems can actually query: a self-hostable ingestion, indexing, storage,
and retrieval layer for a private RAG system, exposed over REST and MCP.

You connect sources — plain text, Markdown, CSV, HTML, JSON, PDF, DOCX,
PNG (OCR) — and Inherent extracts, chunks, embeds, stores, and serves
retrieval with citations, permissions, and freshness signals.

[Get started locally](getting-started/local.md){ .md-button .md-button--primary }
[What's new](release-notes.md){ .md-button }

## Fast routes

| If you need to... | Open this |
| --- | --- |
| Start the system locally and run the first upload/search flow | [Local quickstart](getting-started/local.md) |
| Deploy to a Hetzner VM with Terraform | [Production](getting-started/production.md) |
| Harden the stack before real users/data | [Production hardening](deploy/production.md) |
| Call the API — every endpoint, with curl examples | [API examples](examples/README.md) · [REST API reference](reference/rest-api.md) |
| Wire an agent over MCP | [MCP tools reference](reference/mcp-tools.md) |
| Configure the services | [Configuration reference](reference/configuration.md) |
| See what changed in each release | [Release notes](release-notes.md) |
| Understand the design decisions | [ADR index](adr/README.md) |
| Contribute, report a vulnerability, get help | [Contributing](community/contributing.md) · [Security](community/security.md) · [Support](community/support.md) |

## How it works

Two services, standard components (FastAPI, PostgreSQL, Weaviate, Temporal,
Valkey, S3-compatible storage, Hugging Face TEI):

- **`inh-ingestion-svc`** owns document processing: consumes upload events,
  runs Temporal workflows, extracts, chunks, embeds, and writes to
  PostgreSQL + Weaviate.
- **`inh-public-api-svc`** serves retrieval: REST API and MCP server over
  the indexed content, with per-key permissions, workspace tenancy,
  citations, claim verification, lineage, and traffic-mined retrieval evals.

Run the whole stack with Docker Compose — from source (`make quickstart`)
or from published GHCR images (`docker-compose.release.yml`).
```

- [ ] **Step 5: Create the snippet stub pages**

`docs/release-notes.md`:

```markdown
---
title: Release Notes
---

--8<-- "CHANGELOG.md"
```

`docs/community/contributing.md`:

```markdown
---
title: Contributing
---

--8<-- "CONTRIBUTING.md"
```

`docs/community/code-of-conduct.md`:

```markdown
---
title: Code of Conduct
---

--8<-- "CODE_OF_CONDUCT.md"
```

`docs/community/security.md`:

```markdown
---
title: Security Policy
---

--8<-- "SECURITY.md"
```

`docs/community/support.md`:

```markdown
---
title: Support
---

--8<-- "SUPPORT.md"
```

- [ ] **Step 6: Create the three reference placeholders** (one line each so `--strict` nav resolves; Tasks 2–4 replace them)

`docs/reference/rest-api.md`: `# REST API reference` + one line "Filled in by Task 2."
`docs/reference/mcp-tools.md`: `# MCP tools reference` + one line "Filled in by Task 3."
`docs/reference/configuration.md`: `# Configuration reference` + one line "Filled in by Task 4."

- [ ] **Step 7: First strict build — collect the link failures**

Run: `mkdocs build --strict 2>&1 | tee /tmp/mkdocs-strict.log`
Expected: FAILS with warnings. Known classes you will see:

1. Links inside `CHANGELOG.md` / `CONTRIBUTING.md` / etc. (now rendered via
   stubs) pointing at repo-relative paths like `docs/maintainers/releasing.md`.
2. Links in `docs/**/*.md` pointing outside `docs/` (`../README.md`,
   `../services/...`, `../.github/...`, `../infra/...`).
3. Links in `docs/**/*.md` pointing at `README.md` (excluded hub page).

- [ ] **Step 8: Fix every warning by this decision table**

| Link target | Rewrite to |
| --- | --- |
| From a ROOT file (CHANGELOG/CONTRIBUTING/...) to anything repo-relative | Absolute GitHub URL: `https://github.com/inherent-prime/inherent/blob/main/<path>` (root files render both on GitHub and inside a site page, so only an absolute URL works in both contexts) |
| From `docs/**` to `../README.md` or other root files rendered on-site (CHANGELOG→`release-notes.md`, CONTRIBUTING→`community/contributing.md`, ...) | Relative doc link to the stub page (e.g. `../community/contributing.md`) |
| From `docs/**` to root files NOT on the site or to `../services/`, `../infra/`, `../.github/`, `../Makefile`, source files | Absolute GitHub URL `https://github.com/inherent-prime/inherent/blob/main/<path>` |
| From `docs/**` to `README.md` / `./README.md` (the docs hub) | `index.md` (adjust relative depth, e.g. `../index.md`) |

Re-run `mkdocs build --strict` after each round of fixes until it passes.
If a warning appears that no row covers, fix it in the same spirit
(site-internal targets → relative doc link; repo-internal-only targets →
GitHub blob URL) and note it in the commit message.

- [ ] **Step 9: Verify strict build passes**

Run: `mkdocs build --strict`
Expected: exits 0, `site/` created, no WARNING lines.

- [ ] **Step 10: Add `site/` to `.gitignore`**

Append to `.gitignore`:

```text
# MkDocs build output
site/
```

- [ ] **Step 11: Commit**

```bash
git add mkdocs.yml requirements-docs.txt docs/index.md docs/release-notes.md docs/community/ docs/reference/ .gitignore CHANGELOG.md docs/
git commit -m "docs: add MkDocs Material site scaffold (strict build green)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: REST API reference page

**Files:**
- Modify: `docs/reference/rest-api.md` (replace placeholder)

**Interfaces:**
- Consumes: nav entry + strict build from Task 1.
- Produces: `reference/rest-api.md` linked from `index.md` and (Task 5) `docs/README.md`.

- [ ] **Step 1: Write the page** (content below was extracted from `services/inh-public-api-svc/src/api/**` on 2026-07-14 — spot-check any row you doubt against the named source file before publishing)

```markdown
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
```

- [ ] **Step 2: Strict build**

Run: `mkdocs build --strict`
Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
git add docs/reference/rest-api.md
git commit -m "docs: add REST API reference page

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: MCP tools reference page

**Files:**
- Modify: `docs/reference/mcp-tools.md` (replace placeholder)

**Interfaces:**
- Consumes: nav entry from Task 1.
- Produces: `reference/mcp-tools.md`.

- [ ] **Step 1: Write the page** (extracted from `services/inh-public-api-svc/src/mcp_server/server.py` `_TOOLS` registry on 2026-07-14 — spot-check against the registry before publishing)

```markdown
# MCP tools reference

The public API service ships an MCP server (`inherent-knowledge-base`)
exposing the same capabilities as the REST API with matching permission
enforcement and failure behavior.

## Running & transport

- **Transport: stdio.** Start the service with `SERVICE_MODE=mcp`; the MCP
  server runs as its own process (it is not mounted on the REST app).
- Every tool call carries the API key as a schema argument (`api_key`) —
  there are no transport headers on stdio. The key is validated and the
  tool's permission checked **before** the handler runs, mirroring REST
  401/403 behavior. Handlers additionally enforce workspace ownership.
- Tools, schemas, permissions, and dispatch all derive from a single
  `_TOOLS` registry entry per tool, so the advertised surface cannot drift
  from the enforced one.

## Tools

All tools require `api_key` (string). Additional parameters below.

### Search (`search` permission)

| Tool | Parameters | Purpose | REST twin |
| --- | --- | --- | --- |
| `search_documents` | `query` (required); `workspace_id`, `limit` (10), `min_score` (0.0), `document_ids[]`, `search_mode` (`semantic`/`hybrid`/`keyword`), `alpha` (0.7) | Search chunks; fans out across all owned workspaces when none given | `POST /v1/search` |
| `search_memory` | same as `search_documents` | Memory-primitive alias — identical behavior | `POST /v1/search` |
| `get_citations` | same as `search_documents` | Search returning claim-level citation objects (spans, score, provenance, freshness) | `POST /v1/search` |
| `report_feedback` | `event_id`, `verdict` (`answered`/`partial`/`not_relevant`) required; `useful_chunk_ids[]`, `note` | Record a verdict on a captured search event; builds the workspace eval set | `POST /v1/evals/feedback` |
| `get_retrieval_health` | `workspace_id` (required) | Workspace retrieval scorecard | `GET /v1/evals/scorecard` |

### Read (`read` permission)

| Tool | Parameters | Purpose | REST twin |
| --- | --- | --- | --- |
| `list_documents` | `workspace_id`, `page` (1), `page_size` (20) | Paginated document listing | `GET /v1/documents` |
| `get_document` | `document_id` (required) | Single document's metadata | `GET /v1/documents/{id}` |
| `list_chunks` | `document_id` (required) | All chunks for a document | `GET /v1/chunks/{document_id}` |
| `get_document_context` | `document_id` (required) | Full concatenated chunk text + metadata header | `GET /v1/chunks/{document_id}/context` |
| `verify_claim` | `claim` (required); `evidence[]` | Offline lexical claim-vs-evidence support scoring | `POST /v1/verify-claim` |
| `explain_lineage` | `document_id` (required); `chunk_id` | Provenance + freshness for a document or chunk | `GET /v1/documents/{id}/lineage` |

### Write (`write` permission)

| Tool | Parameters | Purpose | REST twin |
| --- | --- | --- | --- |
| `upload_document` | `filename`, `content` (required); `content_type` (`text/markdown` default — `text/plain`, `text/csv`, `text/html` accepted), `workspace_id` | **Text-only** ingestion sharing REST's validate/dedup/store/enqueue pipeline. Binary formats (PDF/DOCX/PNG) are REST-only — use `POST /v1/documents`. If the key owns several workspaces, `workspace_id` is required | `POST /v1/documents` |
| `delete_document` | `document_id` (required) | Permanently delete document + vectors + chunks + stored bytes | `DELETE /v1/documents/{id}` |
| `refresh_stale_source` | `document_id` (required) | Re-enqueue an uploaded document to clear staleness; on MQ failure the document is marked `failed`, matching REST | `POST /v1/documents/{id}/refresh` |

## Notes

- Search tools do not take `include_context` / `context_window` — use
  `get_document_context` for surrounding text.
- Permissions are exact membership, same as REST: `write` does not imply
  `read` or `search`.
```

- [ ] **Step 2: Strict build**

Run: `mkdocs build --strict`
Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
git add docs/reference/mcp-tools.md
git commit -m "docs: add MCP tools reference page

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Configuration reference page

**Files:**
- Modify: `docs/reference/configuration.md` (replace placeholder)

**Interfaces:**
- Consumes: nav entry from Task 1.
- Produces: `reference/configuration.md`.

- [ ] **Step 1: Write the page** (extracted from both services' `src/config/settings.py`, `embedder.py`, compose files, `.env.example` on 2026-07-14 — spot-check defaults you doubt)

```markdown
# Configuration reference

Operator-facing environment variables, grouped by service. **Secret** marks
credentials. The release stack (`docker-compose.release.yml`) fails fast if
`POSTGRES_PASSWORD`, `INGESTION_API_KEY`, or `WEAVIATE_API_KEY` is unset,
and binds all datastore ports to `127.0.0.1`.

!!! warning "Shared names, different meanings"
    Do not set these globally in a shared `.env` — compose injects them
    per-service:

    - `SERVICE_MODE`: public-api accepts `api`/`mcp`/`both`; ingestion
      accepts `worker`/`standalone`/`migrate`.
    - `API_PORT`: ingestion's standalone port (8000) vs public-api's
      override of `PORT` (8080).
    - `REDIS_URL`: ingestion's MQ backend vs public-api's distributed
      rate-limit store (public-api's MQ is `MQ_REDIS_URL`).

## inh-public-api-svc

### Core

| Variable | Default | Effect |
| --- | --- | --- |
| `SERVICE_MODE` | `both` | `api`, `mcp`, or `both` (`both` starts REST; run MCP as a separate `mcp` process) |
| `PORT` / `API_PORT` | `8080` / unset | HTTP port; `API_PORT` overrides `PORT` when set |
| `MCP_PORT` | `8001` | MCP server port |
| `ENVIRONMENT` | `development` | `development`/`production`; gates HSTS and CORS behavior |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

### Datastores

| Variable | Default | Effect | Secret |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/knowledge_base` | Read-only PostgreSQL connection | yes |
| `MONGODB_URI` | `mongodb://localhost:27017/main` | Read-only Mongo for workspace/user ownership | yes |
| `MONGODB_DB_NAME` | `main` | Mongo database name | no |
| `WEAVIATE_URL` | unset | Full Weaviate URL; overrides host/port below | no |
| `WEAVIATE_HOST` / `WEAVIATE_PORT` | `localhost` / `8080` | Weaviate address when `WEAVIATE_URL` unset | no |
| `WEAVIATE_API_KEY` | unset | Bearer key for Weaviate auth (required by the release stack) | yes |
| `AWS_S3_ENDPOINT` / `AWS_S3_BUCKET` / `AWS_S3_REGION` | `""` / `inherent-documents` / `eu-central-1` | S3-compatible document storage | no |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `""` | S3 credentials | yes |

### MQ & rate limiting

| Variable | Default | Effect | Secret |
| --- | --- | --- | --- |
| `MQ_REDIS_URL` | `redis://localhost:6379` | Redis/Valkey URL for publishing upload events | yes |
| `MQ_UPLOAD_TOPIC` | `core.document.uploaded.v1` | Upload topic — must match the ingestion consumer | no |
| `REDIS_URL` | unset | Redis for distributed rate limiting; in-memory (per-process) fallback when unset | yes |
| `RATE_LIMIT_ENABLED` | `true` | Master toggle (CI/e2e sets `false`) | no |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length | no |
| `RATE_LIMIT_DEFAULT` | `100` | Default per-key limit per window | no |
| `RATE_LIMIT_UNAUTHENTICATED` | `30` | Per-client-IP limit for requests without a valid key | no |
| `TRUSTED_PROXIES` | empty | Proxy IPs whose `X-Forwarded-For`/`X-Real-IP` are trusted | no |

### Search, freshness & embeddings

| Variable | Default | Effect |
| --- | --- | --- |
| `SEARCH_MAX_WORKSPACE_CONCURRENCY` | `8` | Max workspaces searched concurrently per multi-workspace request |
| `FRESHNESS_MAX_AGE_DAYS` | `90` | Evidence older than this is flagged `is_stale` (never filtered) |
| `EMBEDDING_SERVICE_URL` | `http://text-embeddings-inference:80` | TEI sidecar base URL |
| `EMBEDDING_DIM` | `384` | Embedding vector dimension |
| `EMBEDDING_TIMEOUT_S` | `30.0` | Per-request TEI timeout (seconds) |
| `ENABLE_RERANKER` / `ENABLE_GRAPHRAG_INDEX` / `ENABLE_HIERARCHY_INDEX` | `false` | EXPERIMENTAL retrieval scaffolding — off by default, not implemented |

### Evals

| Variable | Default | Effect |
| --- | --- | --- |
| `EVAL_CAPTURE_ENABLED` | `true` | Capture search events for evals (opt-out) |
| `EVAL_RETENTION_DAYS` | `30` | Days raw events are kept before purge |
| `EVAL_CAPTURE_DISABLED_WORKSPACES` | empty | Comma-separated workspace IDs excluded from capture |
| `EVAL_MIN_SAMPLE_SIZE` | `50` | Labeled-case count below which the scorecard flags low confidence |
| `EVAL_RUN_CONCURRENCY` | `4` | Concurrent replay searches per eval run |
| `EVAL_RUN_K` | `5` | Ranking-metric cutoff (recall@k, nDCG@k) |

### Security, CORS & observability

| Variable | Default | Effect |
| --- | --- | --- |
| `API_KEY_HEADER_NAME` | `X-API-Key` | Header carrying the client API key |
| `ENABLE_HSTS` | `true` | Emit HSTS header in production |
| `CORS_ORIGINS` | inherent.systems origins | Allowed origins (wildcard in dev if unchanged) |
| `CORS_ALLOW_CREDENTIALS` / `CORS_ALLOW_METHODS` / `CORS_ALLOW_HEADERS` | `true` / all standard / `*` | CORS details (credentials forced off with wildcard origin) |
| `METRICS_ENABLED` / `METRICS_PATH` | `true` / `/metrics` | Prometheus endpoint |
| `HEALTH_CHECK_TIMEOUT_SECONDS` | `5.0` | Dependency health-check timeout |
| `AUDIT_LOG_ENABLED` / `AUDIT_LOG_TOPIC` | `true` / `audit.log.write` | Audit logging + MQ topic |

## inh-ingestion-svc

### Core

| Variable | Default | Effect | Secret |
| --- | --- | --- | --- |
| `SERVICE_MODE` | `worker` | `worker`, `standalone`, or `migrate` (release init runs migrations) | no |
| `DATABASE_URL` | **required** | PostgreSQL (read/write; migration target). Boot fails if unset | yes |
| `WEAVIATE_URL` | **required** | Weaviate URL. Boot fails if unset | no |
| `WEAVIATE_API_KEY` | unset | Weaviate Bearer key | yes |
| `MONGODB_URI` / `MONGODB_DB_NAME` | `mongodb://localhost:27017` / `main` | Mongo for audit-log writes | yes / no |
| `LOG_LEVEL` | `INFO` | Logging verbosity | no |
| `INGESTION_API_KEY` | unset | Auth secret for the standalone HTTP API (release stack requires it) | yes |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Standalone HTTP API bind | no |
| `METRICS_PORT` | `9090` | Prometheus port in worker mode | no |

### Storage

| Variable | Default | Effect | Secret |
| --- | --- | --- | --- |
| `STORAGE_BACKEND` | `s3` | `s3` / `gcs` / `local` | no |
| `STORAGE_BUCKET` | `""` | Bucket name | no |
| `AWS_S3_ENDPOINT` / `AWS_REGION` | unset / `nbg1` | S3-compatible endpoint + region | no |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | unset | S3 credentials | yes |

### MQ

| Variable | Default | Effect | Secret |
| --- | --- | --- | --- |
| `MQ_BACKEND` | `redis` | `redis` / `pubsub` / `memory` | no |
| `REDIS_URL` | `redis://localhost:6379` | Valkey/Redis URL (when backend is `redis`) | yes |
| `MQ_UPLOAD_TOPIC` | `core.document.uploaded.v1` | Consumed upload topic — must match publisher | no |
| `MQ_COMPLETION_TOPIC` | `core.document.processed.v1` | Processed-document event topic | no |
| `MQ_CONSUMER_GROUP` | `ingestion-workers` | Consumer group | no |
| `MQ_MAX_CONCURRENT` | `0` (→ `MAX_WORKERS`) | Backpressure: max in-flight workflow starts | no |

### Processing, embeddings & retries

| Variable | Default | Effect |
| --- | --- | --- |
| `CHUNKING_STRATEGY` | `sentences` | `tokens` / `sentences` / `paragraphs` |
| `MAX_CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `200` | Chunk sizing |
| `EMBEDDING_ENABLED` | `true` | Toggle embedding generation |
| `EMBEDDING_SERVICE_URL` / `EMBEDDING_DIM` | `http://text-embeddings-inference:80` / `384` | TEI sidecar |
| `EMBEDDING_MAX_TOKENS` | `512` | Hard token budget per chunk (bge-small context window) |
| `EMBEDDING_BATCH_SIZE` / `EMBEDDING_TIMEOUT_S` | `32` / `30.0` | Chunks per TEI call / per-request timeout |
| `MAX_WORKERS` / `MAX_RETRIES` / `RETRY_DELAY_SECONDS` | `4` / `3` / `5` | Worker concurrency and retry policy |

### Temporal & tenancy

| Variable | Default | Effect |
| --- | --- | --- |
| `TEMPORAL_ENABLED` | `false` | Enable Temporal orchestration |
| `TEMPORAL_HOST` / `TEMPORAL_NAMESPACE` / `TEMPORAL_TASK_QUEUE` | `localhost:7233` / `default` / `document-ingestion` | Temporal wiring |
| `TEMPORAL_MAX_CONCURRENT_ACTIVITIES` / `TEMPORAL_MAX_CONCURRENT_WORKFLOW_TASKS` | `10` / `10` | Concurrency caps |
| `TEMPORAL_AUDIT_NAMESPACE` / `TEMPORAL_AUDIT_TASK_QUEUE` | `audit` / `audit-writer-queue` | Audit workflow wiring |
| `TENANT_IDLE_DAYS` | `30` | Inactivity days before a Weaviate tenant is deactivatable |
| `AUTO_CREATE_TENANTS` | `true` | Auto-create tenants on first upload |
| `AUDIT_LOG_TOPIC` / `AUDIT_CONSUMER_GROUP` | `audit.log.write` / `ingestion-audit-writers` | Audit MQ wiring |

## Compose / infrastructure

Consumed by compose interpolation or upstream images, not the Python services:

| Variable | Default | Effect | Secret |
| --- | --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_DB` | `postgres` / `knowledge_base` | Postgres identity + DB | no |
| `POSTGRES_PASSWORD` | dev `postgres`; **release: required** | Postgres password (embedded into `DATABASE_URL`) | yes |
| `WEAVIATE_API_KEY` | dev `local-dev-weaviate-key`; **release: required** | Configures Weaviate's accepted keys AND both clients | yes |
| `EMBEDDING_MODEL_ID` | `BAAI/bge-small-en-v1.5` | Model the TEI sidecar loads | no |
| `INHERENT_REGISTRY` / `INHERENT_VERSION` | `ghcr.io/inherent-prime` / `latest` | Release-stack image source + tag | no |

## Not configurable via environment

Hard-coded in `services/inh-public-api-svc/src/config/constants.py` (change
requires a code change): plan rate limits (starter 100 / pro 500 / team 2000 /
enterprise 10000), max upload size (50 MB), allowed MIME types,
search/pagination bounds.
```

- [ ] **Step 2: Strict build**

Run: `mkdocs build --strict`
Expected: exits 0.

- [ ] **Step 3: Commit**

```bash
git add docs/reference/configuration.md
git commit -m "docs: add configuration reference page

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Docs hub routing update

**Files:**
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: pages created in Tasks 1–4.
- Produces: hub rows other docs/agents rely on.

- [ ] **Step 1: Add rows to the Fast Routes table in `docs/README.md`** (after the existing "Copy request examples" row)

```markdown
| Look up every REST endpoint, permission, and shape | [reference/rest-api.md](reference/rest-api.md) |
| Look up every MCP tool, schema, and REST twin | [reference/mcp-tools.md](reference/mcp-tools.md) |
| Look up operator env vars and defaults | [reference/configuration.md](reference/configuration.md) |
| See what changed in each release | [release-notes.md](release-notes.md) (renders the root CHANGELOG) |
```

- [ ] **Step 2: Update the Folder Map** in the same file — add under `docs/`:

```text
  index.md                     docs-site landing page (published)
  reference/
    rest-api.md                REST endpoint reference
    mcp-tools.md               MCP tool reference
    configuration.md           operator env-var reference
  release-notes.md             site page rendering the root CHANGELOG.md
  community/                   site pages rendering root CONTRIBUTING/CoC/SECURITY/SUPPORT
```

Also add one line after the Folder Map noting: "The `mkdocs.yml` at the repo
root publishes this tree to GitHub Pages; `mkdocs build --strict` must stay
green (CI: `.github/workflows/docs.yml`)."

- [ ] **Step 3: Strict build + commit**

Run: `mkdocs build --strict` → exits 0.

```bash
git add docs/README.md
git commit -m "docs: route hub to reference pages and release notes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Docs CI — build check on PRs, deploy to Pages on main

**Files:**
- Create: `.github/workflows/docs.yml`

**Interfaces:**
- Consumes: `mkdocs.yml`, `requirements-docs.txt` from Task 1.
- Produces: the `Docs` check that CLAUDE.md (Task 7) declares must stay green.

- [ ] **Step 1: Create `.github/workflows/docs.yml`**

```yaml
name: Docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "requirements-docs.txt"
      - "CHANGELOG.md"
      - "CONTRIBUTING.md"
      - "CODE_OF_CONDUCT.md"
      - "SECURITY.md"
      - "SUPPORT.md"
      - ".github/workflows/docs.yml"
  pull_request:
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "requirements-docs.txt"
      - "CHANGELOG.md"
      - "CONTRIBUTING.md"
      - "CODE_OF_CONDUCT.md"
      - "SECURITY.md"
      - "SUPPORT.md"
      - ".github/workflows/docs.yml"

permissions:
  contents: read

concurrency:
  group: docs-${{ github.ref }}
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements-docs.txt
      - run: mkdocs build --strict
      - uses: actions/upload-pages-artifact@v3
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        with:
          path: site

  deploy:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: build
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Validate the YAML parses**

Run: `python3 -c "import yaml, sys; yaml.safe_load(open('.github/workflows/docs.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Check action versions against existing workflows** — run
`grep -h "uses:" .github/workflows/ci.yml | sort -u` and align
`actions/checkout` / `actions/setup-python` major versions with what the repo
already uses if they differ.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci: build docs on PRs, deploy to GitHub Pages on main

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

**Manual follow-up for the user (note it in the final report, do not attempt):**
Repo Settings → Pages → Source: **GitHub Actions** (one-time). Optional:
custom domain `docs.inherent.sh` (README already links it) — set the domain
there + DNS CNAME, then change `site_url` in `mkdocs.yml`.

---

### Task 7: CLAUDE.md — Release Tagging & Docs rules + dogfood changelog entry

**Files:**
- Modify: `CLAUDE.md` (new section after "## General Guidance")
- Modify: `CHANGELOG.md` (`[Unreleased]` section)

**Interfaces:**
- Consumes: the `Docs` CI check name from Task 6.
- Produces: the process rules Task 8's releasing.md refers to.

- [ ] **Step 1: Add this section to `CLAUDE.md`** (insert between "## General Guidance" and "## Coding Standards")

```markdown
## Release Tagging & Docs

- Every merged PR that changes behavior, API surface, configuration, or
  deployment MUST add a one-line entry under `[Unreleased]` in
  `CHANGELOG.md`, in a Keep a Changelog category (Added / Changed / Fixed /
  Deprecated / Removed / Security), ending with `(#PR, #issue)` refs.
  Docs-only, CI-only, and test-only changes are exempt. Cutting a release =
  renaming `[Unreleased]` to the version — this is how every piece of work
  is tagged to a release and categorized.
- Update the docs a change invalidates (site pages under `docs/`, reference
  pages, examples) in the same PR — the `Docs` CI check must stay green. At
  release time the docs are already current: releasing is rename + tag +
  publish (see [docs/maintainers/releasing.md](docs/maintainers/releasing.md)),
  never a catch-up docs sweep.
```

- [ ] **Step 2: Replace the `[Unreleased]` body in `CHANGELOG.md`** ("Nothing yet." →)

```markdown
### Added

- **Documentation site.** MkDocs Material site published to GitHub Pages
  from `docs/`, with REST API / MCP tools / configuration reference pages
  and on-site release notes rendered from this changelog. New `Docs` CI
  check builds with `--strict` on every PR. Release tagging + docs-currency
  rules added to `CLAUDE.md` and `docs/maintainers/releasing.md`.
```

- [ ] **Step 3: Strict build + commit**

Run: `mkdocs build --strict` → exits 0 (the changelog renders on-site).

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: add release-tagging and docs-currency rules to CLAUDE.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: releasing.md — changelog cut, GitHub Release, docs verify steps

**Files:**
- Modify: `docs/maintainers/releasing.md`

**Interfaces:**
- Consumes: CLAUDE.md rules from Task 7.
- Produces: the canonical release procedure.

- [ ] **Step 1: Update the "Release Checklist" section** — replace step 4
("Summarize user-visible changes in the release notes or tag message.") with:

```markdown
4. Cut the changelog: rename `[Unreleased]` in `CHANGELOG.md` to
   `[X.Y.Z] — YYYY-MM-DD — <one-line theme>` and add a fresh empty
   `[Unreleased]` above it. Lead the new section with a 2–3 bullet
   **TL;DR** before the category headings. Thanks to the CLAUDE.md
   release-tagging rule, every shipped change is already listed — do not
   reconstruct history at release time.
5. Publish the GitHub Release after pushing the final tag:
   ```bash
   gh release create vX.Y.Z --verify-tag \
     --title "vX.Y.Z — <one-line theme>" \
     --notes-file <notes.md>
   ```
   Distill the notes from the changelog section: TL;DR first, then
   Added/Changed/Fixed, then **Upgrade notes** (new migrations, new/changed
   env vars, breaking changes). `-rcN` tags get `--prerelease`.
6. Verify the `Docs` workflow deployed green on `main` and the site's
   Release Notes page shows the new version.
```

Renumber the old step 5 ("Tag from a clean commit history...") to sit before
the new step 5 (order: checklist 1–3 unchanged, 4 cut changelog, 5 tag from
clean history, 6 publish GitHub Release, 7 verify docs site). Keep the
existing "Publishing Images" section unchanged.

- [ ] **Step 2: Strict build + commit**

Run: `mkdocs build --strict` → exits 0.

```bash
git add docs/maintainers/releasing.md
git commit -m "docs: add changelog cut, GitHub Release, and docs-verify steps to releasing.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Publish GitHub Releases for v0.4.1 and v0.5.0

**Files:**
- Create (scratchpad, not committed): `/tmp` release-notes files — use the session scratchpad directory, e.g. `<scratchpad>/v0.4.1-notes.md`, `<scratchpad>/v0.5.0-notes.md`

**Interfaces:**
- Consumes: CHANGELOG.md content (verbatim source for the notes).
- Produces: public GitHub Releases visible on the repo's Releases tab.

- [ ] **Step 1: Write `v0.4.1` notes file**

```markdown
Out-of-band `inh-ingestion-svc` hotfix (0.4.0 → 0.4.1).

## Fixed

- **Ingestion failed permanently on NUL bytes in extracted text (#84).**
  PostgreSQL rejects the NUL (0x00) byte in `text` columns, so extraction
  retried deterministically and the workflow failed, leaving the document
  stuck with no chunks or embeddings. The `extract_text` activity now strips
  NUL bytes after the quality check runs (the diagnostic still sees the raw
  signal) and before staging; an entirely-NUL document still fails the
  empty-text guard.

Full details: [CHANGELOG.md](https://github.com/inherent-prime/inherent/blob/main/CHANGELOG.md)
```

- [ ] **Step 2: Write `v0.5.0` notes file**

```markdown
The org-readiness release — a milestone-by-milestone push (M0–M7) to make
Inherent a self-hostable, permission-aware agent memory substrate an
organization can run on day one. First repository-level tag published since
v0.4.1. Package versions: `inh-contracts` 2.0.0, `inh-ingestion-svc` 0.5.0,
`inh-public-api-svc` 0.2.0.

## TL;DR

- **Evals v1**: turn real search traffic + agent feedback into a labeled
  eval set, then score recall@k / MRR / nDCG across keyword, semantic, and
  hybrid modes on your own corpus — no golden-set authoring.
- **Complete REST ↔ MCP parity**: document delete, text upload,
  `get_document`, `list_chunks`, single-chunk fetch — full CRUD + retrieval
  on both surfaces with matching failure behavior.
- **⚠️ Two breaking changes** (see Upgrade notes): hardened release compose
  (deploy) and collision-free Weaviate naming (data — re-index required).

## Added

- Traffic-mined retrieval evals (#91): search responses carry an
  `event_id`; `POST /v1/evals/feedback` (MCP `report_feedback`) promotes
  positive verdicts into labeled cases; `POST /v1/evals/runs` replays them
  as a mode comparison; `GET /v1/evals/scorecard` (MCP
  `get_retrieval_health`) gives the day-one summary. Migration
  `015_evals.sql`. Design boundary in ADR 0003.
- Document delete on REST + MCP (#87 P1): `DELETE /v1/documents/{id}` /
  `delete_document` remove vectors, rows + chunks, and stored bytes through
  one orchestrator, retry-safe.
- Full REST ↔ MCP parity (#87 P2/P3, #96): single-chunk fetch, MCP
  `get_document` / `list_chunks` / `upload_document` (text formats; binary
  stays REST-only by design).
- REST ↔ MCP failure-parity contract suite and CLAUDE.md defect-prevention
  rules from the #98/#99/#100 retrospective.

## Changed

- MCP tools are declared once in a `_TOOLS` registry — advertisement,
  permission enforcement, and dispatch cannot drift (#100). No behavior
  change.

## Fixed

- Re-uploading identical content no longer re-indexes it (#109); also
  un-blocked the Compose e2e release gate.
- Compensating mark-failed writes retried with backoff; exhaustion is
  CRITICAL-logged and counted, never silently orphaned (#99).
- MCP `refresh_stale_source` marks the document failed on MQ outage instead
  of stranding it `pending` (#98).
- Completion events restored in worker mode (#88); lineage table ships with
  migrations (#89); idle Redis polls silenced (#90); content-hash dedup
  collapses verbatim re-uploads (#75); search no longer 500s on
  not-yet-indexed workspaces.

## Security / Breaking

- **⚠️ BREAKING (data):** collision-free Weaviate collection/tenant naming
  (base32) fixes a cross-tenant leak (#1). Existing collections use old
  names — drop + re-ingest to migrate. PostgreSQL unaffected.
- **⚠️ BREAKING (deploy):** `docker-compose.release.yml` refuses to start
  without `POSTGRES_PASSWORD` and `INGESTION_API_KEY`; datastores bind to
  `127.0.0.1` only; Weaviate runs with API-key auth — set
  `WEAVIATE_API_KEY`.
- Workspace-scoped keys can no longer cross workspaces via
  `X-Workspace-Id`; unauthenticated traffic is rate-limited per client IP
  (`RATE_LIMIT_UNAUTHENTICATED`).

## Upgrade notes

- Run migrations — `010`, `014`, `015` are new since 0.4.x (the release
  stack's `postgres-init` runs them via `SERVICE_MODE=migrate`).
- Set `POSTGRES_PASSWORD`, `INGESTION_API_KEY`, `WEAVIATE_API_KEY` before
  `docker compose up`.
- Re-index Weaviate content (drop + re-ingest) for the naming migration.
- New optional env vars: `EVAL_CAPTURE_ENABLED`, `EVAL_RETENTION_DAYS`,
  `EVAL_CAPTURE_DISABLED_WORKSPACES`, `RATE_LIMIT_UNAUTHENTICATED`,
  `REDIS_URL` (distributed rate limiting).

Full details: [CHANGELOG.md](https://github.com/inherent-prime/inherent/blob/main/CHANGELOG.md)
```

- [ ] **Step 3: Publish both releases** (order matters — create older first so "latest" lands on v0.5.0)

```bash
gh release create v0.4.1 --verify-tag \
  --title "v0.4.1 — ingestion-svc NUL-byte hotfix" \
  --notes-file <scratchpad>/v0.4.1-notes.md
gh release create v0.5.0 --verify-tag --latest \
  --title "v0.5.0 — Org-readiness program" \
  --notes-file <scratchpad>/v0.5.0-notes.md
```

Do NOT create releases for `v0.1.0`, `v0.1.0-rc1`, `v0.5.0-rc1` (never fully
published / superseded candidates).

- [ ] **Step 4: Verify**

Run: `gh release list`
Expected: two rows; `v0.5.0` marked `Latest`.

---

### Task 10: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full strict build from a clean tree**

Run: `rm -rf site && mkdocs build --strict`
Expected: exits 0, no warnings.

- [ ] **Step 2: Serve and spot-check**

Run: `mkdocs serve -a 127.0.0.1:8801` (background), then verify these return
200 and contain expected content:

```bash
curl -s http://127.0.0.1:8801/ | grep -c "private company brain"          # ≥1
curl -s http://127.0.0.1:8801/release-notes/ | grep -c "0.5.0"            # ≥1
curl -s http://127.0.0.1:8801/reference/rest-api/ | grep -c "/v1/search"  # ≥1
curl -s http://127.0.0.1:8801/reference/mcp-tools/ | grep -c "search_documents"  # ≥1
curl -s http://127.0.0.1:8801/reference/configuration/ | grep -c "EVAL_RETENTION_DAYS"  # ≥1
curl -s http://127.0.0.1:8801/community/contributing/ | grep -ci "contribut"  # ≥1
```

Kill the server afterwards.

- [ ] **Step 3: Adversarial pass (CLAUDE.md rule)** — re-read the full diff
(`git diff main...HEAD`) checking: no hosted/future behavior documented, no
secrets in examples, reference tables match the extraction notes, releasing.md
steps are internally consistent, CLAUDE.md section doesn't contradict existing
rules.

- [ ] **Step 4: Report** — summarize: build output, spot-check results,
`gh release list` output, and the one manual follow-up (Settings → Pages →
Source: GitHub Actions; optional `docs.inherent.sh` custom domain).
```
