# Testing

This repository is a monorepo of three Python packages, each with its own test
suite and `pytest` configuration:

- `services/inh-public-api-svc` — customer-facing API + MCP server
- `services/inh-ingestion-svc` — document ingestion service
- `services/inh-contracts` — shared event + naming contracts

Every test command below assumes you have synced dev dependencies first:

```bash
make install      # syncs dev deps for both Python services
# or, per service:
cd services/<svc> && uv sync --extra dev --group dev
```

Tool versions (pytest, pytest-asyncio, pytest-cov, ruff, black, mypy, bandit)
are normalized across all three services — see
[docs/developer/dependencies.md](developer/dependencies.md).

## Default behavior

Both services default to **excluding Compose-backed tests** via `addopts`
(`-m 'not compose'`), so a bare `uv run pytest` is safe to run on a laptop with
no Docker stack up. Coverage (`--cov`) is on by default in both services.

## Test profiles

Run these from the relevant service directory (`cd services/<svc>`).

### Fast unit (innermost loop)

Skips Compose, slow, and benchmark tests — the quickest signal:

```bash
uv run pytest -m 'not compose and not slow and not benchmark'
```

Repo-wide shortcut:

```bash
make test-fast        # runs the fast profile across both services
```

### Default (offline)

The full offline suite for a service (Compose tests already excluded by
`addopts`):

```bash
uv run pytest                 # uses each service's default -m 'not compose'
# explicit equivalent:
uv run pytest -m 'not compose'
```

Repo-wide shortcut:

```bash
make test             # pytest for both services
```

### End-to-end / Compose

Requires a running local stack (`make dev` or `docker compose up`). These hit
real Postgres / Weaviate / Redis / S3 and are the release e2e gate:

```bash
uv run pytest -m compose
```

Repo-wide shortcut:

```bash
make test-integration   # public-api compose suite (stack must be up)
```

**Local compose CI:** `.github/workflows/integration.yml` (or `make test-integration`
against a laptop stack).

**Hetzner production-path e2e:** `.github/workflows/hetzner-e2e.yml` — Terraform
apply on Hetzner (remote state key `inherent/ci/<run_id>/terraform.tfstate`),
bootstrap, then public-api `pytest -m compose` against the VM. Not a PR gate.

- **Triggers:** successful **Publish images** on a final `vX.Y.Z` tag
  (`workflow_run`; RCs skipped), or manual `workflow_dispatch` with `ref`.
- **Pin:** same tag for checkout, GHCR `inherent_version` (`X.Y.Z`), and
  `compose_git_ref`. No weekly / `:latest` schedule.
- **Secrets:** `HCLOUD_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
- **Variables:** `HETZNER_S3_BUCKET`, `HETZNER_S3_ENDPOINT`, optional
  `AWS_DEFAULT_REGION` (default `eu-central`).
- **Recover orphans:** `.github/workflows/hetzner-e2e-recover.yml` (`run_id`
  input).

See [infra/README.md](../infra/README.md#ci-e2e) and
[releasing](maintainers/releasing.md#cutting-an-image-release).

## Markers

Markers are declared in each service's `[tool.pytest.ini_options].markers`.
Combine them with `-m` expressions (e.g. `-m 'security or contract'`).

| Marker             | Meaning                                                            | Services |
| ------------------ | ----------------------------------------------------------------- | -------- |
| `unit`             | Fast, isolated unit tests                                          | all      |
| `integration`      | Exercises real service dependencies                               | public-api, ingestion |
| `compose`          | Requires a running docker-compose stack (deselected by default)   | public-api, ingestion |
| `slow`             | Slow-running tests                                                 | public-api, ingestion |
| `benchmark`        | Latency/throughput benchmarks (loose SLO regression guards)       | public-api, ingestion |
| `security`         | Auth/tenancy security regression tests (offline)                  | public-api, ingestion |
| `contract`         | REST/MCP/schema contract regression (shapes, permissions, codes)  | all      |
| `retrieval_eval`   | Retrieval quality and ranking regression benchmarks               | public-api |
| `eval`             | Fixture-backed extraction/chunking quality evaluations            | ingestion |
| `failure_injection`| Intentional dependency-failure tests                              | ingestion |

### Specialized examples

```bash
# Security regressions (offline)
cd services/inh-public-api-svc && uv run pytest -m security

# REST/MCP contract regressions
cd services/inh-public-api-svc && uv run pytest -m contract

# Retrieval quality benchmarks
cd services/inh-public-api-svc && uv run pytest -m retrieval_eval

# Ingestion extraction/chunking evaluations
cd services/inh-ingestion-svc && uv run pytest -m eval

# Ingestion dependency-failure injection
cd services/inh-ingestion-svc && uv run pytest -m failure_injection

# Benchmarks (either service)
cd services/<svc> && uv run pytest -m benchmark
```

## Coverage

Coverage is enabled by default (`--cov=src --cov-report=term-missing`). To run
without it (faster, or to avoid coverage gates while iterating):

```bash
uv run pytest --no-cov
```

## Release gate

The suites that must pass before tagging — and how to run them in one shot via
`make release-check` — are documented in
[docs/maintainers/release_acceptance_matrix.md](maintainers/release_acceptance_matrix.md).
