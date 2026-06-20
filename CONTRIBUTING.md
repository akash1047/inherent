# Contributing

Thanks for contributing to the Inherent OSS core.

## Before You Start

- Read the root [README.md](README.md) for repository scope.
- Keep changes aligned with the OSS boundary. Do not add internal tooling, secrets, or private operational workflows.
- Prefer small pull requests with a clear problem statement.

## Local Setup

### Repository-Level Checks

The shortest path is the repository-root `Makefile`, which runs the documented
checks for **both** services from one place:

```bash
make install        # sync dev deps for both services
make check          # validate + lint + format-check + type-check + security + test
```

You can also run any single stage across both services:

```bash
make lint           # Ruff
make format-check   # Black --check
make type-check     # mypy (services that enable it)
make security-check # Bandit (services that enable it)
make test           # pytest for both services
```

Run `make help` to list every target. Service-specific commands remain
available below when you only need to touch one service.

### Ingestion Service

```bash
cd services/inh-ingestion-svc
uv sync --extra dev --group dev
uv run ruff check src tests
uv run black --check src tests
uv run pytest
```

### Public API Service

```bash
cd services/inh-public-api-svc
uv sync --extra dev --group dev
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
uv run bandit -c pyproject.toml -r src
uv run pytest
```

For end-to-end local service runs, start the shared dependency stack from the repository root:

```bash
cp .env.example .env
docker compose up --build
```

### Validating Your `.env`

`.env.example` is the canonical reference for every env var the Compose stack
and both services read. Values tagged `# LOCAL-ONLY` (e.g. `POSTGRES_PASSWORD`,
`AWS_ACCESS_KEY_ID=S3RVER`, `INGESTION_API_KEY=dev-ingestion-key`) are
development placeholders and must never be reused in production.

To check a local `.env` against both service settings before starting Compose
or running a service on the host, run from the repository root. The script
imports both services' `Settings` classes, so it needs `pydantic` and
`pydantic-settings` available. Use a service venv (or `uv run`):

```bash
# via uv (recommended — auto-resolves the venv)
uv --project services/inh-ingestion-svc run python scripts/validate_env.py

# or directly via the service venv
services/inh-ingestion-svc/.venv/bin/python scripts/validate_env.py
```

If you see `cannot import (missing dependency 'pydantic')`, sync the venv
first: `cd services/inh-ingestion-svc && uv sync --extra dev --group dev`.

The script loads `.env` from the repository root (cwd does not matter),
instantiates the `Settings` classes from both services, and reports:

- missing required values (`DATABASE_URL`, `WEAVIATE_URL`)
- cross-service inconsistencies (mismatched `EMBEDDING_DIM`, region drift,
  MQ topic divergence, `SERVICE_MODE` literal collision)
- URLs pointing at Compose-internal hostnames (`postgres`, `weaviate`, …),
  which only resolve inside the Compose network; use the published host
  ports listed in `.env.example` when running services on the host.

Exits non-zero on any blocking issue (missing required vars, etc.).

## Codebase Graph (Graphify)

Graphify output (`graphify-out/`) is local and generated — it is listed in `.gitignore` and must not be committed.

Install once via `uv tool install graphifyy` (PyPI package name is `graphifyy` — double y; the CLI command is `graphify`):

```bash
uv tool install graphifyy
```

Code files are always extracted locally via tree-sitter (no API key needed). To build or refresh the graph:

```bash
graphify .          # full build
graphify . --update # re-extract changed files only
```

To include semantic extraction of docs, PDFs, and images, export an API key before running:

```bash
export ANTHROPIC_API_KEY=<your-key>
graphify .
```

## Pull Request Expectations

- Explain the problem and the approach.
- Update docs when behavior, setup, or repository boundaries change.
- Keep README and service-specific docs consistent.
- Run `make check` (or the relevant service checks) before opening a PR.

## Issue Reports

- Use GitHub issues for reproducible bugs and scoped feature requests.
- Use [SUPPORT.md](SUPPORT.md) for usage questions and general support routes.
- Use [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Scope Guidelines

Good contributions:

- bug fixes
- documentation corrections
- developer experience improvements
- test coverage improvements
- incremental API and ingestion enhancements that fit the existing OSS core

Changes that usually need maintainer discussion first:

- major architecture shifts
- new infrastructure dependencies
- repository-wide tooling changes
- features that depend on private or non-OSS product services
