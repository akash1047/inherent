# Dependency & Dev-Tooling Conventions

This monorepo contains three Python packages, each with its own
`pyproject.toml` and `uv.lock`:

- `services/inh-public-api-svc`
- `services/inh-ingestion-svc`
- `services/inh-contracts`

This document describes how runtime and dev dependencies are declared so the
three stay consistent and `uv sync` is reproducible.

## Package manager

All services use [uv](https://docs.astral.sh/uv/). Sync a service with:

```bash
uv --project services/<svc> sync --extra dev --group dev
```

or from inside the service directory:

```bash
cd services/<svc> && uv sync --extra dev --group dev
```

`make install` runs this for both Python services.

## Where dev dependencies live

Each service declares its dev tooling in **two** places that are kept in sync:

1. `[project.optional-dependencies].dev` — the canonical, PEP 621 dev extra.
2. `[dependency-groups].dev` — the uv dependency group (PEP 735).

Both lists carry the **same pinned versions**. We keep both so that
`uv sync --extra dev --group dev` (the command used by `make install` and CI)
resolves to identical versions regardless of which flag is passed, and so
either the extra or the group alone still produces the documented toolchain.

> When you change a dev tool version, update **both** lists in **all three**
> services so they cannot drift.

## Normalized tool versions

Dev tooling is pinned to exact versions and aligned across all three services
(M7 #21). The shared set:

| Tool             | Version  |
| ---------------- | -------- |
| `pytest`         | 9.0.2    |
| `pytest-asyncio` | 1.3.0    |
| `pytest-cov`     | 7.0.0    |
| `ruff`           | 0.14.10  |
| `black`          | 24.10.0  |
| `mypy`           | 1.19.1   |
| `bandit[toml]`   | 1.9.3    |
| `pre-commit`     | >= 3.6.0 |

Rationale:

- **Exact pins (`==`)** for linters/formatters/type-checkers/test runners so a
  passing local run matches CI and pre-commit byte-for-byte. Previously these
  used floors (`>=`), which let `uv` pull newer releases independently per
  service — Black/Ruff/mypy had drifted across the three packages, producing
  different format/lint results depending on which service you were in.
- `black==24.10.0` is the version the public API already pinned and that the
  whole repo is formatted against; the others were matched to it.
- `pre-commit` keeps a floor (`>=`) because it is an orchestrator, not a
  formatter — its exact version does not change lint/format output.

Service-specific dev deps stay local to the service that needs them, e.g.
`playwright` and `types-redis` in `inh-public-api-svc`. The `ocr` extra in
`inh-ingestion-svc` is runtime-optional and unrelated to dev tooling.

## Updating tool versions

1. Bump the version in **both** `[project.optional-dependencies].dev` and
   `[dependency-groups].dev` of **all three** services to the same value.
2. `uv --project services/<svc> sync --extra dev --group dev` for each service.
3. Verify nothing broke (per service):
   ```bash
   uv run ruff check src tests
   uv run black --check src tests
   uv run pytest -m 'not compose'
   ```
4. If a bump introduces new lint/format findings, either fix the code or revert
   that single bump — do not land a version change that breaks `make check`.
5. Commit the updated `uv.lock` files alongside the `pyproject.toml` changes.

## Pre-commit

The repo-root [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml) is the
canonical hook set and shells out to each service's `uv run`, so hooks always
use the pinned versions above. See [CONTRIBUTING.md](../../CONTRIBUTING.md) for
install/run instructions.
