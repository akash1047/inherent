# Contributing

Thanks for contributing to the Inherent OSS core.

## Before You Start

- Read the root [README.md](README.md) for repository scope.
- Keep changes aligned with the OSS boundary. Do not add internal tooling, secrets, or private operational workflows.
- Prefer small pull requests with a clear problem statement.

## Local Setup

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

## Pull Request Expectations

- Explain the problem and the approach.
- Update docs when behavior, setup, or repository boundaries change.
- Keep README and service-specific docs consistent.
- Run the relevant local checks before opening a PR.

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
