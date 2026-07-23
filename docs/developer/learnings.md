---
search:
  exclude: true
---

# Engineering Learnings

Durable lessons from defects that survived to `main`. CLAUDE.md references
this file — read the matching entry before touching the related area. Add an
entry when a shipped defect teaches something a rule alone can't carry: one
entry per root cause, newest first.

## #146 — A single-probe readiness wait races the rest of the corpus it's gating (2026-07-24)

**Defect.** `test_compose_retrieval_regression.py`'s corpus-readiness wait
checked exactly ONE query ("wait until the corpus is searchable" == wait
until the *first* query in the golden corpus dict returns *any* result),
then immediately scored every other query in the corpus. On a slow/CPU-only
embedding runner, the probe's own document can finish extract->chunk->embed
->index well before the rest of the corpus does — so scoring started while
most documents were still mid-pipeline, and every query backed by a
not-yet-indexed document legitimately scored zero, not because ranking was
bad but because there was nothing there yet to rank. This had already
shipped: the committed `corpus/retrieval_history.jsonl`'s first entry (sha
`201363a`, the real baseline this branch's Phase 1 work seeded from) shows
the signature exactly — `exact_id`/`stale_version` (3 small fixtures) scored
a perfect 1.0 while `general`/`paraphrase` (the bulk of the corpus,
competing for the same embedding-worker time) scored near zero, in every
mode uniformly. The same race was independently observed live during #146
development: a freshly-added query scored 0/0/0 on the first run and a
perfect 1.0/1.0/1.0 on an immediate re-run with no code change in between.
It surfaced via a `/cross-review` pass questioning why the committed
baseline jumped ~4x between two history entries, not from anyone noticing
the original low number was wrong at the time it was recorded.

**Learnings.**

- A "wait until ready" check that only probes ONE representative item is a
  race whenever readiness isn't atomic across the whole set — it proves
  *a* document is ready, not *the* document a given assertion needs. If N
  independent things must all be ready before an assertion runs, the wait
  must check all N (or the specific ones each assertion depends on), not
  one stand-in for all of them.
- A suspiciously uniform low score across every mode/metric in an eval
  report (here: near-identical `recall@5`/`mrr`/`ndcg@5` around 0.05-0.21 for
  every search mode) is a signature worth checking against harness
  correctness before accepting it as a real quality measurement, especially
  when a subset of categories score perfectly and the rest score near zero —
  that split usually means "some things weren't there yet," not "ranking is
  uniformly bad here but great there."
- A number silently seeded into a governance gate (a baseline, a threshold)
  from one run is only as trustworthy as the harness that produced it; a
  harness bug upstream of the metric computation doesn't fail loud — it just
  produces a technically-valid but wrong number that then gets ratcheted on.

**Mandatory pattern.** Any live-stack eval/benchmark that waits for
"corpus ready" before scoring must check readiness per-query (or per
fixture) against what THAT query specifically depends on, not a single
probe for the whole corpus — see `test_compose_retrieval_regression.py`'s
`_query_ready` (requires each query's own judged-relevant document, or any
result for a by-design abstention query, before including it in scoring).

## #139 — A CI job that pushes to a protected branch fails silently, forever (2026-07-23)

**Defect.** `eval-baseline-ratchet` computed a correct ratcheted baseline on
every green `main` run, then tried to `git push origin HEAD:main`. Branch
protection on `main` requires a status check the direct push can never
satisfy, so every attempt failed with `remote rejected (protected branch hook
declined)` — for every run since the job shipped. The job's own retry loop
(5 attempts, re-fetch and reset each time) made this look like transient
contention, but the failure was structural, not a race: nothing about
retrying changes what branch protection rejects. `corpus/retrieval_baseline.json`
stayed at its seeded zeros the whole time, so the relative regression gate
was a no-op — only the absolute `RETRIEVAL_MIN_RECALL5` floor was ever live.
The job did fail loudly in CI (by design, per its own comment), but a
red job on a job nobody expects to matter for merge (`eval-baseline-ratchet`
runs post-merge on `main`/nightly, never blocks a PR) reads as background
noise, not an incident — it went unnoticed until an unrelated eval-hardening
pass re-derived the baseline from source and diffed it against zeros.

**Learnings.**

- A CI job that writes back to a protected branch needs a push path that
  branch protection actually allows — a PAT/GitHub App token with a bypass,
  or (what this fix uses) open a PR and let the normal required check run,
  rather than pushing directly and hoping protection doesn't apply to bots.
  Retrying a rejected push is never the fix; branch protection isn't a race
  condition.
  A red job whose failure mode is "runs post-merge, never blocks anything"
  needs an explicit owner/alert, or a structural failure hides for as long as
  the job keeps quietly failing in the same way. If a CI job's only visible
  effect of failing is a red run nobody is looking at, that job's *success*
  needs to be verified once, deliberately — not assumed from "the step
  exists and doesn't crash."
- The PR-based fix has its own edge cases, caught only by cross-model review
  (`/cross-review`) before this ever ran in CI, not by writing the code
  carefully the first time: `gh pr view <branch>` matches an already-merged
  PR on a reused branch just as readily as an open one, so checking for "a PR
  exists" instead of "an *open* PR exists" reintroduces the exact same
  silent-stop failure one layer up, after exactly one successful merge.
  Reusing a branch across runs also means a not-yet-merged run's state can be
  silently discarded by the next run if that next run rebuilds from `main`
  instead of from the open PR's own tip. And `--force-with-lease` protects
  nothing if the remote ref it leases against was never fetched — the push
  it's meant to guard just gets rejected as stale instead. None of these are
  exotic: they are the default behavior of `gh pr view`, `git checkout -B
  <branch> origin/main`, and `git push --force-with-lease` respectively: each
  needed exercising against the "PR already exists" and "PR still open" cases
  specifically, not just the first-run case.
- The default `GITHUB_TOKEN` cannot be used to make a CI job's *own* fix
  self-verifying: GitHub explicitly excludes pushes/PRs made with it from
  triggering other workflow runs, so a job that opens a PR with `github.token`
  and expects `ci.yml` to pick it up will never see that check fire. A
  same-repo elevated token (PAT or GitHub App installation token, added as a
  scoped secret) is required for a CI-authored PR to trigger a required
  check by itself; this is a permissions/trust boundary GitHub enforces on
  purpose, not a bug to route around.

**Mandatory pattern.** Any workflow job that writes generated/ratcheted state
back to `main` (baseline files, changelogs, lockfiles) must do so via a PR +
optional auto-merge (see `eval-baseline-ratchet` in
`.github/workflows/integration.yml`), never via `git push origin HEAD:<protected-branch>`.
That PR path must (a) check for an *open* PR specifically before deciding
whether to create one, (b) fetch the reused branch before force-pushing to it
and before deciding whether to reset vs. pull its state forward, and (c) use
an elevated token (not the default `GITHUB_TOKEN`) if the PR is expected to
trigger its own required check without human intervention.

## #112 — Writing release notes is not the same as publishing them (2026-07-13)

**Defect.** `v0.5.0` shipped with a well-written annotated tag message and a
matching `CHANGELOG.md` entry, but neither is where a consumer looks first.
No tag — `v0.1.0`, `v0.4.1`, `v0.5.0` — had ever been published as a GitHub
Release, so the Releases tab was empty. Separately, the GHCR package page for
both images showed "No description provided": `publish.yml`'s "Build and
push" step passed `labels: ${{ steps.meta.outputs.labels }}` but not
`annotations:`, and for a multi-platform build GHCR's package UI reads OCI
annotations on the manifest index, not labels baked into each per-arch image
config — so the metadata `docker/metadata-action` generated never reached the
registry UI.

**Learnings.**

- Writing content and publishing it to the surface people actually check are
  two different steps. A checklist item that says "summarize changes" is
  satisfied by content existing *somewhere*; it needs to name the destination
  (Releases tab, package page) or it will be satisfied by content nobody
  finds.
- Multi-platform image metadata has two independent channels — `labels`
  (per-arch image config) and `annotations` (manifest index) — and a registry
  UI may read only one of them. When a build-push-action step consumes a
  `metadata-action` output for one, check whether it should also consume the
  other.

**Mandatory pattern.** `docs/maintainers/releasing.md`'s checklist has an
explicit "publish a GitHub Release from the tag" step; do not consider a
release's notes done until that Release exists. `publish.yml`'s "Build and
push" step passes both `labels:` and `annotations:` from `steps.meta.outputs`
for both services — do not drop `annotations:` when touching that step.

## #99 — A compensating write is itself a fallible step (2026-07-12)

**Defect.** `intake_document` marked a document `failed` after an MQ publish
failure, but wrapped the mark in log-and-swallow. When the DB also blipped,
the row stayed `pending` while the client saw `failed` — an orphan no
recovery process could find. The pattern sweep found the identical swallow at
all three compensation sites: upload intake (shared REST + MCP), REST
refresh, MCP refresh.

**Learnings.**

- Compensation code runs exactly when infrastructure is already failing, so
  it is the code *most* likely to fail. It needs retry and loud exhaustion —
  more care than the happy path, not less.
- A state write inside an `except` block that is itself wrapped in
  `try/except`-log is the signature of this defect. Grep for it in review.
- An `xfail` test pins a missing contract but masks its own rot: the #99
  xfail hid a stale patch target (the #87 refactor moved
  `get_storage_service` out of the module the test patched), so the test was
  failing for the wrong reason and nobody saw. When removing an `xfail`
  marker, first prove the test fails for the documented reason.

**Mandatory pattern.** Route every compensating mark through
`services/inh-public-api-svc/src/services/compensation.py::mark_document_failed_with_retry`
— 3 attempts, exponential backoff; exhaustion emits a CRITICAL log
(document_id + workspace_id for reconciliation) and bumps
`document_compensation_exhausted_total{operation}`. Never call
`database.mark_document_failed` bare inside an `except` block. The contract
lives in `tests/contract/test_failure_parity.py` (upload + refresh, both
surfaces).

**Alerting.** Alert on any increase of
`document_compensation_exhausted_total`. Each increase is one document
orphaned as `pending` that needs manual reconciliation via the paired
CRITICAL log line.
