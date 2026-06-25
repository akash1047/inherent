# CLAUDE.md

Guidance for AI assistants (Claude Code and others) working in this repository.

## What this is

**Inherent** is the OSS core of a private RAG / "agent memory substrate" — the
ingestion, indexing, storage, and retrieval layer for turning company knowledge
into something AI agents can query. The product boundary, guarantees, and
non-goals are defined in [`docs/adr/0001-agent-memory-substrate.md`](docs/adr/0001-agent-memory-substrate.md);
read it before proposing larger changes.

This is a **monorepo of three Python packages** under `services/`:

| Package | Role |
| --- | --- |
| `inh-ingestion-svc` | Write/admin plane. Consumes upload events, runs Temporal ingestion workflows (fetch → extract → chunk → embed → store), owns writes to PostgreSQL and Weaviate. Also exposes an HTTP admin API. |
| `inh-public-api-svc` | Read/query plane. Customer-facing REST API + MCP server over indexed content. Reads from PostgreSQL/Weaviate, enqueues upload events for ingestion. |
| `inh-contracts` | Shared, versioned source of truth for cross-service event schemas (`events.py`) and Weaviate naming (`naming.py`). Both services depend on it. |

Data flow: documents → ingestion (extract/chunk/embed/index) → PostgreSQL
(metadata + chunks) and Weaviate (vectors) → public API (search/retrieve) →
clients. See the architecture diagram in [`README.md`](README.md).

## Architecture notes that matter

- **`inh-contracts` is the anti-drift boundary.** The two services MUST agree
  byte-for-byte on Weaviate collection/tenant names and event schemas. If you
  change naming or event shapes, change them in `inh-contracts` only — both
  services import from there, and contract tests assert the golden behavior
  (e.g. `ws_local_001 -> Workspace_wslocal001`, `user_001 -> User_user001`).
  `events.CONTRACT_VERSION` pins the schema semver; keep older messages
  validating (backward compat) when you bump it.
- **Multi-tenancy:** workspaces map to Weaviate collections, users to tenants
  within them. See [`docs/adr/0002-weaviate-multi-tenancy-scale.md`](docs/adr/0002-weaviate-multi-tenancy-scale.md).
- **Control plane:** MongoDB holds workspace ownership (control-plane truth);
  PostgreSQL `api_keys` holds API keys. The public API needs both records
  before any upload/search works — `make bootstrap` creates them locally.
- **Ingestion service modes** (`SERVICE_MODE`): `worker` (default in Compose —
  Temporal worker + MQ + metrics + HTTP API when `INGESTION_API_KEY` set) and
  `standalone` (HTTP API only). Legacy names (`pubsub`, `temporal_worker`, …)
  map to `worker`.
- **Public API service modes** (`SERVICE_MODE`): `api`, `mcp` (stdio), `both`
  (Compose default).
- **Ingestion is Temporal-orchestrated.** The pipeline lives in
  `inh-ingestion-svc/src/temporal/` (`workflows/` define orchestration,
  `activities/` do the work). Don't put long-running or retryable work outside
  an activity.

## Local development

Prerequisites: Docker + Docker Compose, Python 3.11+, and [`uv`](https://docs.astral.sh/uv/).

The repository-root `Makefile` is the canonical entrypoint — run `make help`
for the full list. Common targets:

```bash
make quickstart   # fresh checkout → working stack (env + install + up + bootstrap)
make dev          # start Compose in background + bootstrap dev workspace/key
make health       # check both API health endpoints
make logs         # follow stack logs (SVC=name to scope)
make down         # stop the stack
make clean        # stop + remove volumes
```

`make bootstrap` (run by `quickstart`/`dev`) is **local/dev only**, safe to
re-run, and creates the dev workspace + API key `ink_dev_local_key_001` in both
PostgreSQL and MongoDB.

Local endpoints (host ports are offset, e.g. Postgres on `15432`): Public API
`:18000` (docs at `/docs`), Ingestion API `:18002`, Temporal UI `:18233`,
Weaviate `:18080`, S3/`s3rver` `:19000`, MongoDB `:27018`, Valkey `:16379`.

`.env.example` is the canonical reference for every env var. Values tagged
`# LOCAL-ONLY` are dev placeholders and must never be reused in production.
Validate a local `.env` with `make validate`.

## Checks — always run before committing

`make check` runs the full suite for **both** services. Individual stages:

```bash
make lint            # ruff check src tests
make format-check    # black --check src tests
make type-check      # mypy (public API only — ingestion not yet enabled)
make security-check  # bandit (public API only)
make test            # pytest for both services
```

CI (`.github/workflows/ci.yml`) runs lint + format + typecheck + security +
test per service with an overall coverage floor (currently 40% ingestion, 45%
public API) plus per-core-module floors that ratchet up over time. The
Compose-backed e2e gate runs separately in `integration.yml`.

Tooling config (per service `pyproject.toml`): Ruff and Black both use
**line-length 100**, target `py311`. Ruff selects `E,F,I,N,W` and ignores
`E501`. mypy and Bandit adoption is gradual (some modules excluded) — don't
expand strictness opportunistically without intent.

### Test profiles and markers

```bash
make test-fast        # fast offline unit profile (not compose/slow/benchmark)
make test             # default offline pytest (excludes compose)
make test-integration # Compose e2e — requires a running stack
make release-check    # offline release-acceptance suites (contract/security/eval/failure_injection)
```

`-m 'not compose'` is the default in both services' `addopts`; Compose tests
are opt-in. Markers include `unit`, `integration`, `compose`, `slow`,
`security`, `contract`, `benchmark`, and service-specific ones (`eval`,
`failure_injection`, `retrieval_eval`). Full reference in
[`docs/testing.md`](docs/testing.md).

### Working in a single service

Each service is a standalone `uv` project. From its directory:

```bash
cd services/inh-public-api-svc      # (or inh-ingestion-svc)
uv sync --extra dev --group dev
uv run ruff check src tests
uv run black --check src tests
uv run mypy src                     # public API only
uv run pytest
```

Dev tool versions are **pinned and normalized across all services** — see
[`docs/developer/dependencies.md`](docs/developer/dependencies.md). Don't bump a
pin in one service without the others.

## Service layout (mirrored in both services)

```text
src/
  api/          FastAPI routes (public API: api/v1/*)
  config/       Settings (pydantic-settings) and constants
  core/         Shared exceptions / response helpers (public API)
  middleware/   Auth, rate limiting, audit logging, security headers, errors
  models/       Pydantic request/response models
  services/     DB, search, embedder, storage, MQ, metrics, auth logic
  temporal/     Workflows + activities (ingestion only)
  mcp_server/   MCP server (public API only — note: NOT `mcp/`, to avoid
                shadowing the `mcp` SDK package)
  utils/        Logging, validators
  main.py       Entrypoint; dispatches on SERVICE_MODE
tests/          Mirrors src/; markers per pyproject
```

## Conventions

- **Commits:** Conventional Commits with scopes, e.g. `fix(search): …`,
  `feat: …`, `docs(examples): …`, `ci: …`, `chore(dx): …`, `test(contract): …`.
  Reference issue numbers where relevant (`(#45)`).
- **Branches:** descriptive prefixes like `fix/…`, `bug/…`, `milestone/…`.
- **Pre-commit:** root `.pre-commit-config.yaml` runs file hygiene + per-service
  Ruff/Black (and mypy/Bandit for public API) via `uv run`. Install once:
  `uv --project services/inh-public-api-svc run pre-commit install`.
- **Async throughout:** both services are async FastAPI; tests use
  `asyncio_mode = "auto"`. New I/O code should be async.
- **Logging:** `structlog` (structured). Don't `print`.
- **Scope discipline (OSS boundary):** don't add internal tooling, secrets,
  private operational workflows, or non-OSS product dependencies. See
  [`docs/maintainers/repository-boundaries.md`](docs/maintainers/repository-boundaries.md)
  and [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Docs stay consistent:** when behavior, setup, or boundaries change, update
  `README.md`, the relevant service `Readme.md`, and `docs/`. Update
  `CHANGELOG.md` for user-visible changes.
- `graphify-out/` is local/generated and gitignored — never commit it.

## Where to look

- API examples / curl / Postman: [`docs/examples/README.md`](docs/examples/README.md)
- Getting started walkthrough: [`docs/getting-started/local.md`](docs/getting-started/local.md)
- Architecture decisions: [`docs/adr/`](docs/adr/)
- Testing reference: [`docs/testing.md`](docs/testing.md)
- Docs index (agent-first): [`docs/README.md`](docs/README.md)
