# Engineering Learnings

Durable lessons from defects that survived to `main`. CLAUDE.md references
this file — read the matching entry before touching the related area. Add an
entry when a shipped defect teaches something a rule alone can't carry: one
entry per root cause, newest first.

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
