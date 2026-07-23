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

**Laptop Hetzner VM (manual):** [getting-started/local-vm-test.md](getting-started/local-vm-test.md)
— Terraform apply from your machine with Object Storage remote state, smoke
`/health`, optional bootstrap and `pytest -m compose`. Destroy when done.

**Hetzner production-path e2e:** `.github/workflows/hetzner-e2e.yml` — Terraform
apply on Hetzner (remote state key `inherent/ci/<run_id>/terraform.tfstate`),
bootstrap, then public-api `pytest -m compose` against the VM. Not a PR gate.

- **Triggers:** successful **Publish images** on a final `vX.Y.Z` tag
  (`workflow_run`; RCs skipped), or manual **Run workflow** form.
- **Form / inputs:** [infra/README.md § Manual run](https://github.com/inherent-prime/inherent/blob/main/infra/README.md#manual-run-github-form)
  — `ref` (required; checkout + compose; needs `infra/`), optional
  `inherent_version` (GHCR tag), `server_type` (default `cpx32`). “Use workflow
  from” only selects the workflow YAML branch.
- **Pin:** prefer aligned image tag + checkout when testing a release; use
  `ref=main` + explicit `inherent_version` when the release tag lacks `infra/`.
- **Secrets:** `HCLOUD_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
- **Variables:** `HETZNER_S3_BUCKET`, `HETZNER_S3_ENDPOINT`, optional
  `AWS_DEFAULT_REGION` (default `eu-central`).
- **Recover orphans:** `.github/workflows/hetzner-e2e-recover.yml` (`run_id`
  input) — same infra README section.
- **Local `act`:** optional laptop simulation of the workflow; see infra README
  § Local simulation and [audit/act-hetzner-e2e-weaviate-401.md](audit/act-hetzner-e2e-weaviate-401.md).
  Smoke image parity before long runs ([releasing](maintainers/releasing.md#hetzner-act-e2e-image-parity)).

See [infra/README.md](https://github.com/inherent-prime/inherent/blob/main/infra/README.md#ci-e2e) and
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

## Retrieval-eval gate, baseline ratchet, and trend history (#139)

`test_compose_retrieval_regression.py` (`retrieval_eval` + `compose`) hard-gates
on regression, not just reporting: any per-mode metric (recall@5/MRR/nDCG@5)
that drops more than `EVAL_GATE_TOLERANCE` (default `0.02`) below the committed
`corpus/retrieval_baseline.json` fails the build, via
`tests/evals/eval_gate.py`. An absolute-floor backstop
(`RETRIEVAL_MIN_RECALL5`, default `0.15`) still applies underneath it.

On a green gate on `main`, `.github/workflows/integration.yml`'s
`eval-baseline-ratchet` job ratchets the baseline up to
`max(current, baseline)` per mode/metric (never down), appends a line to
`corpus/retrieval_history.jsonl` — a durable, checked-in trend log of every
main-branch run's scores — and opens (or updates) a pull request carrying both
changes, rather than pushing to `main` directly: branch protection rejects
direct `github-actions[bot]` pushes, so a push-based ratchet silently fails
every run (this is what left the baseline seeded at zeros for the entire time
#139 was live — see the history log's first entry for the real numbers it was
seeded with instead). The job reuses one branch
(`chore/ratchet-retrieval-baseline`) across runs; it checks for an **open** PR
specifically (`gh pr list --state open`, not `gh pr view`, which also matches
an already-merged PR on the same branch and would otherwise skip
`gh pr create` forever after the first merge) and, if one is open, pulls that
PR's own baseline/history forward before recomputing rather than resetting to
`main`'s older copy, so a not-yet-merged rise is never silently dropped. The
PR is opened with auto-merge requested so a clean ratchet still needs no human
action, but falls back to a normal maintainer-merged PR if auto-merge isn't
enabled on the repo — the same fallback applies if the optional
`RATCHET_PR_TOKEN` repo secret (a PAT or GitHub App token with
`contents:write`+`pull-requests:write`) isn't configured, since the default
`GITHUB_TOKEN` is excluded from triggering other workflow runs on the push/PR
it creates and the PR's required check (`ci.yml`) won't fire on its own
without it. On gate failure (push-to-main or nightly), the
`eval-regression-alert` job files or updates an issue labeled
`retrieval-eval-regression`. This does **not** gate PRs — the full Compose
stack stays too slow/expensive to run on every PR (see the note at the top of
`integration.yml`); regressions are caught post-merge, same as the rest of
this workflow.

The golden corpus (`corpus/qrels.jsonl`) tags each judgment with an optional
`category`: `general`, `exact_id`, `stale_version`, `paraphrase`, `abstention`
(a query with no relevant document — the correct signal is zero recall/MRR/
nDCG, not a fabricated match), or `multi_doc_crowding` (a query with 2+
genuinely relevant documents where one has many more chunks than the other —
`q14`, `rate-limiting-deep-dive.txt` (5 chunks) vs.
`rate-limit-quick-reference.txt` (1 chunk) — exercising the scenario
per-document diversification, #146, exists to fix: a naive score-sorted
top-k can crowd the shorter document out entirely). Per-category scores are
printed and written to the eval report (`_by_category`) for visibility; only
the per-mode pooled averages are gated, and `abstention` queries are excluded
from that pool since they can never contribute a positive score by
construction. Permission/tenancy boundaries are deliberately not a category
here — that's owned by the `security` marker suite, not this ranking-quality
corpus.

## Benchmark JSON report artifacts (REQ-EVL-3)

The live Compose benchmarks (`benchmark` + `compose`, both services) each
write a JSON summary alongside printing to stdout, so a run's numbers survive
past the CI log — same principle as the retrieval-eval report above, not just
for retrieval:

- **public-api search benchmarks** (`test_search_latency_throughput.py`) write
  `search-benchmark-report.json` with `search_latency` (p50/p95/p99/min/max
  ms) and `search_throughput` (QPS) keys, each carrying the commit SHA the run
  measured. `tests/benchmark/run_search_benchmark.py::write_benchmark_report`
  merges rather than overwrites, since both tests share one file within a run;
  the standalone CLI (`run_search_benchmark.py`) writes the same shape under a
  `cli_search` key via its own `--report` flag.
- **ingestion throughput benchmark** (`test_ingestion_throughput.py`) writes
  `ingestion-benchmark-report.json` with an `ingestion_throughput` key
  (`docs_per_sec`, `elapsed_s`, `batch_size`, commit SHA), via the sibling
  `tests/benchmark/benchmark_report.py` helper (duplicated rather than shared
  across services — separate Python packages, no common dependency between
  them).

Both are uploaded as CI artifacts (`search-benchmark-report`,
`ingestion-benchmark-report`) by `integration.yml`'s `compose-integration` job,
`if: always()` so a benchmark failure still leaves the partial numbers
retrievable. Override the output path locally with the `BENCHMARK_REPORT` env
var. These are visibility only — no CI gate reads them back; the loose
SLO assertions already in the tests are what fails the build on a gross
regression.

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
