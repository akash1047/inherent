# ADR 0005 — ZIP Archive Expansion: Fan-Out Contract

- **Status:** Accepted
- **Date:** 2026-08-06
- **Deciders:** maintainers
- **Closes:** #130
- **Related:** [ADR 0001](0001-agent-memory-substrate.md), #110, #117

## Context

An agent that holds a bundle (repo export, docs folder) as one ZIP must today
upload every member individually. ZIP support means one uploaded archive
becomes N ingested documents — a fan-out the pipeline was not built for.
Three existing contracts assume one-document-per-upload and must each get an
explicit answer, not an implicit one:

1. **`DocumentUploadMessage`** (`services/inh-contracts/src/inh_contracts/events.py:22-126`,
   contract v1.0.0) carries exactly one `document_id`. Nothing in the schema
   or its consumer (`trigger.py`) expects a message to represent more than
   one document.
2. **Workflow ids are fixed per document.** `TemporalWorkflowTrigger` starts
   every ingestion at `id=f"ingest-{upload_message.document_id}"`
   (`services/inh-ingestion-svc/src/temporal/trigger.py:284`, `:424`). #110
   (`docs/developer/learnings.md:13-166`) spent three rounds fixing what
   happens when a second event collides with that id: `TERMINATE_EXISTING`
   supersedes the running workflow
   (`trigger.py:51`, `:296-298`, `:447-449`), and a database-level fencing
   token (`processed_documents.active_run_id` / `active_run_claimed_at`,
   migrations `016_active_run_fencing.sql` / `017_active_run_claim_ordering.sql`,
   guarded at write time in
   `services/inh-ingestion-svc/src/services/database.py:851-899`) stops the
   terminated run's already-dispatched store activity from clobbering the
   newer run's content, because terminating a Temporal workflow does not
   stop work it already dispatched. Any fan-out design that mints new kinds
   of ids inherits this exact hazard from scratch unless it reuses the
   mechanism #110 already built and proved.
3. **Dedup is content- and filename-keyed, per workspace.** `intake_document`
   (`services/inh-public-api-svc/src/services/document_intake.py:130-198`)
   hashes the upload, looks up `get_document_id_by_content_hash` (workspace,
   content_hash) first, then `get_document_id_by_filename`
   (`services/inh-public-api-svc/src/services/database.py:293-364`), and
   reuses the existing `document_id` — including a same-content short-circuit
   that skips re-ingestion entirely
   (`document_intake.py:160-190`). A fan-out design must say whether a member
   is a first-class participant in this dedup contract or a second, weaker
   one.

`FILE_TYPE_REGISTRY` (`services/inh-contracts/src/inh_contracts/file_types.py`,
#117) is the fourth contract in scope, and it already anticipates this ADR:
its `extensions` field is documented as reserved for "a future
extension-based consumer (e.g. #130's ZIP member classification)"
(`file_types.py:116-118`), and its `docx` entry's magic-byte comment already
states that a bare 4-byte ZIP signature (`PK\x03\x04`) cannot distinguish a
ZIP from an OOXML sibling and "disambiguating... needs inspecting the
archive's internal `[Content_Types].xml`" (`file_types.py:233-241`) — the
same ambiguity a member classifier must resolve.

## Decision

**Expansion happens once, synchronously, at REST intake — before any MQ
message or Temporal workflow exists.** `POST /v1/archives` (new endpoint,
REST-only per the issue's proposed surface) reads the uploaded ZIP's central
directory, applies the limits below, and then calls the *existing*
`intake_document` pipeline once per admitted member — unmodified. Each
member becomes one ordinary `DocumentUploadMessage` and one ordinary
`ingest-{document_id}` workflow. Nothing about a member's journey through MQ,
Temporal, storage, or dedup is special-cased; only the intake step that
produces those N calls is new.

### 1. Fan-out: N ordinary messages, not one message that fans out inside the workflow

Rejected alternative: keep the archive as one `DocumentUploadMessage` and
fan out to N documents inside `DocumentIngestionWorkflow`. This was rejected
because:

- `DocumentIngestionInput` is single-document shaped end to end
  (`services/inh-ingestion-svc/src/temporal/models.py:19-36`) — teaching the
  workflow to write N `processed_documents` rows from one input duplicates,
  inside the workflow, exactly the dedup/validation logic
  `intake_document` already owns on the REST side, and now two call sites
  must agree on it (the surface-friction pattern this repo has been bitten
  by before, e.g. #9, #100).
- The dedup lookups (`get_document_id_by_content_hash`,
  `get_document_id_by_filename`) live in `inh-public-api-svc`'s
  `DatabaseService`, not `inh-ingestion-svc`'s. Fanning out inside the
  workflow means either duplicating those queries into ingestion-svc's
  `DatabaseService` (a second implementation of #75's dedup contract) or
  reaching back into public-api-svc from a Temporal activity — both worse
  than doing the lookup once, where it already lives, before any message is
  published.
- Zip-bomb limits (below) are cheap to enforce against ZIP central-directory
  metadata without inflating member bytes. Enforcing them matters most
  *before* paying for decompression, S3 upload, and a Temporal workflow
  start per member — i.e. at intake, not after a workflow has already been
  scheduled.

**Consequence of this choice: `DocumentUploadMessage` does not change.**
Contract v1.0.0 stays byte-for-byte as it is; no `parent_document_id` field,
no schema version bump. A member is indistinguishable, on the wire, from a
document uploaded standalone. The only new persistent concept is the
archive's own bookkeeping row (below), which never touches MQ or Temporal.

### 2. Identity and dedup: a member is a full peer of a standalone upload

A member's `document_id` is resolved by calling the *same*
`get_document_id_by_content_hash` → `get_document_id_by_filename` →
`uuid4()` fallback chain `intake_document` already runs
(`document_intake.py:142-198`), keyed on `(workspace_id, content_hash)` /
`(workspace_id, original_filename)` exactly as today. **Two different
archives containing the same file, uploaded into the same workspace, collapse
onto the same document_id** — content-hash dedup does not know or care that
the bytes arrived inside a ZIP. This is not a new policy; it is the existing
#75 contract applied without exception. A member's `original_filename` is
its full path *within* the archive (e.g. `notes/todo.md`, not `todo.md`), so
two same-named members in different folders of one archive do not collide
against each other under filename dedup, and so provenance stays legible.

Rejected alternative: archive-scoped dedup (a document identity keyed on
`(archive_id, member_path)` instead of workspace content). Rejected because
it would let the same byte-identical file be ingested, chunked, and embedded
once per archive it happens to appear in — the exact duplication #75 exists
to prevent — and because it requires a second dedup index with its own
consistency rules alongside the one that already exists.

### 3. The re-upload / #110 interaction — the sharpest edge, resolved by construction

**What happens when a re-uploaded archive re-expands:** for every member
whose bytes are unchanged between the two archive uploads, content-hash dedup
resolves the *same* `document_id` both times
(`document_intake.py:142-144`). Re-publishing `document.uploaded` for that
`document_id` while its prior workflow is still open is **the identical race
#110 already solved** — `TemporalWorkflowTrigger` supersedes the running
`ingest-{document_id}` execution (`TERMINATE_EXISTING`,
`trigger.py:290-299`), and the `active_run_id` / `active_run_claimed_at`
fencing pair (`database.py:851-899`, `:1006-1109`) guarantees the terminated
run's late store write is skipped rather than clobbering the new run's
content. **No new fencing code is required at the member level** — a
re-expanded archive's members hit exactly the same collision-and-supersede
path an ordinary rapid re-upload or `/refresh` call already exercises today,
covered by the existing `test_reindex_fencing.py` suite.

For a member whose bytes *changed* between the two archive uploads,
content-hash dedup misses (a new hash), but *filename* dedup still resolves
the same `document_id` (`document_intake.py:146-148`) — this is #60's
edited-content-reindex behavior, again unmodified. For a member that is
*new* in the second archive (added since the first upload), a fresh
`document_id` is minted; there is no prior run to collide with.

**The archive's own bookkeeping row (Decision 4) never participates in this
race at all**, because it is never given a Temporal workflow: it is written
once at intake and re-derived (never mutated in place) on every read. A
second upload of "the same" archive gets a brand-new `archive_id` — archive
identity is not deduped in v1 (Decision 4) — so there is no archive-level
collision to fence in the first place. All of the interesting concurrency
this ADR has to answer for happens at the member/`document_id` layer, where
#110 already owns it.

### 4. Archive bookkeeping: a derived-status envelope, not a second state machine

A new `archive_uploads` table (additive migration, filed as a follow-up
issue) stores, once, at intake: `archive_id` (uuid), `workspace_id`,
`user_id`, `original_filename`, `admitted_member_document_ids` (JSONB array),
`skipped_members` (JSONB array of `{path, reason}`), `created_at`. A new
nullable `parent_archive_id` column on `processed_documents` (additive)
links each admitted member's row back to its archive.

**Archive status is computed on every `GET /v1/archives/{archive_id}` from
the current `status` of its member rows — it is never itself written.**

- Any admitted member `status = 'pending'` → archive `pending` (still in
  flight; the response still lists each member's current status
  individually, so a caller is never blind to an early failure just because
  the archive as a whole isn't final).
- No member `pending`, all `processed` → archive `complete`.
- No member `pending`, all `failed` → archive `failed`.
- No member `pending`, a mix of `processed` and `failed` → archive
  `partial`.

Rejected alternative: maintain a stored `status` column on `archive_uploads`,
updated by a new consumer of `document.processed` / `document.failed`.
Rejected because **no such consumer exists today** — `DocumentCompletionMessage`
is published for `intg-svc`, an external system, to update its own MongoDB
(`services/inh-contracts/src/inh_contracts/events.py:129-134`); nothing
inside this repo subscribes to it. Building one is a second, independently
fallible write path that must itself be reconciled if it drifts from the
member rows it summarizes — exactly the state/response divergence class
CLAUDE.md's defect-prevention rules exist to keep out. A derived read has no
divergence to have: it is definitionally always consistent with the member
rows it just queried.

### 5. Partial failure: 9 of 10 members succeed, 1 fails

The archive's status is `partial` (Decision 4). The response body from
`GET /v1/archives/{archive_id}` enumerates all 10 admitted members with each
one's own `document_id` and `status`; the caller reads exactly which member
failed and can retry that document individually (`POST /v1/documents/{id}/refresh`,
existing) without re-uploading the archive. **A failed member follows the
existing single-document failure path unmodified**: its own workflow run
marks it `failed` and publishes `document.failed`
(`services/inh-ingestion-svc/src/temporal/workflows/document_ingestion.py:496`,
`:534`, `:612`) — no new compensation code is needed because a member
failure is not a new failure mode, it is document ingestion failing the way
it already can, once per member instead of once per request.

**Skipped is not failed.** A member with an unsupported type, or a nested
archive (Decision 6), is never admitted — it is recorded in
`archive_uploads.skipped_members` at intake time and never gets a
`document_id`, an S3 object, or a workflow. This mirrors the
skip/fail distinction #117 already draws between "no registry entry" (a
contract-level rejection) and "extraction raised" (an execution-level
failure) — applied per member instead of per request, because fan-out
changes the blast radius of one bad member from "the whole upload 400s" to
"the archive admits 9 of 10 and says so."

### 6. Limits — zip-bomb guards, checked before decompression

All four checked from ZIP central-directory metadata (`ZipInfo.file_size`,
`ZipInfo.compress_size` — read without inflating any member) before any
member's bytes are decompressed, so a hostile archive is rejected for the
cost of an `O(member count)` metadata scan, not the decompression work the
limits exist to prevent:

| Limit | Value | Why |
|---|---|---|
| Archive (compressed) size | 50 MB — the existing `MAX_UPLOAD_SIZE_BYTES` (`services/inh-public-api-svc/src/config/constants.py:75`) | No override; the archive itself is one REST upload and already subject to the global cap. |
| Member count | 500 | Bounds the worst case of one REST request enqueueing 500 Temporal workflow starts + 500 MQ publishes; comfortably above a real docs-folder/repo-export bundle. |
| Total uncompressed size across all members | 500 MB (10x the compressed cap) | Bounds decompression amplification while allowing a legitimately large bundle; a 10x average ratio is far above what prose/code/PDF content compresses to. |
| Per-member compression ratio | 100:1 (`file_size / compress_size`) | Standard zip-bomb heuristic; a single member exceeding it fails the whole archive before any bytes are inflated, not just that member. |

Exceeding any limit rejects the whole upload with `400 Bad Request` before
`archive_uploads` gets a row — this is an intake-time rejection like any
other `BadRequestError` in `intake_document`, not a partial-failure archive
state.

### 7. Nesting: depth 0 — a ZIP member that is itself an archive is never expanded

A member whose extension or sniffed bytes resolve to the ZIP family (`.zip`,
or any OOXML sibling once #118/#119 land, since they share `PK\x03\x04`) is
**skipped, not recursed into** — recorded in `skipped_members` with reason
`"nested archive"`. This is a depth limit of zero, not a depth *counter*: no
recursion budget exists to exhaust, so there is nothing a nested-bomb
attacker can tune against. Revisiting this needs a real use case (an agent
that genuinely bundles archives-of-archives) and a scoped follow-up, not a
default-on recursive expander.

### 8. Member classification through FILE_TYPE_REGISTRY

A ZIP member has no HTTP `Content-Type` header — only a path inside the
archive. Classification therefore runs **extension-first**: `get_spec_for_extension`
(`file_types.py:283-293`, already reserved for exactly this per the
docstring cited in Context) resolves the member's extension to a
`FileTypeSpec`, and the member's own bytes are then sniffed against that
spec's `magic` the same way `sniff_content_type` sniffs a declared REST
`Content-Type` — reusing the check, not the entry point (a ZIP member has no
`declared_mime` to pass in; the extension-resolved spec's canonical MIME
type fills that role). A member whose extension is unregistered, or whose
sniff disagrees, is skipped with the specific reason recorded — never
silently dropped, matching the issue's proposal. A `.docx` member is
unambiguous under this scheme even though its magic bytes collide with plain
ZIP (`file_types.py:233-241`), because extension resolves it before magic
bytes are ever consulted — the exact ambiguity that comment flags is not
reachable here.

The registry itself needs one additive change, left to the follow-up issue:
`FileTypeSpec` gains a way to mark an entry as a *container* (e.g. `zip`
registered with `surfaces=frozenset({"rest"})`, no single-document
`extractor`) so REST-level validation and docs generation see it, while
`test_every_registry_extractor_key_is_wired`
(`services/inh-ingestion-svc/tests/test_temporal_activities.py`) is updated
to exclude container entries — a ZIP archive is never itself dispatched to
an ingestion-svc extractor, because it never becomes a `document_id` of its
own (Decision 1).

## Boundary: what this is not

- **Not a new event contract.** `DocumentUploadMessage` v1.0.0 is unchanged;
  no consumer of that contract needs to change to support ZIP.
- **Not a new fencing mechanism.** Member-level re-ingestion races are the
  existing #110 collision, unmodified. The archive envelope has no fencing
  because it has no workflow to fence.
- **Not recursive.** A ZIP inside a ZIP is a skipped member, not a second
  level of fan-out.
- **Not MCP.** REST-only, per the issue's proposed surface — MCP's
  `upload_document` tool is inline-UTF-8-text-only by construction
  (`file_types.py:66-70`) and cannot transport a ZIP's binary bytes at all.
- **Not a change to single-document upload.** `POST /v1/documents` and
  `intake_document` are called BY the archive path per member, unchanged;
  nothing about a standalone upload's behavior differs after this ADR.

## Consequences

- `intake_document` gains exactly one new caller (the archive expansion
  loop) and zero new branches — the dedup, storage, pending-row, and MQ-publish
  logic a member goes through is the same code, same tests, same failure
  modes as a standalone upload.
- The #110 fencing/supersede mechanism gets its guarantees exercised at
  higher volume (up to 500 concurrent member workflows per archive) but not
  extended — its existing test suite (`test_reindex_fencing.py`) is the
  correctness bar a re-uploaded archive must clear, not a new one.
- New schema surface: `archive_uploads` (new table) and
  `processed_documents.parent_archive_id` (new nullable column), both
  additive migrations, filed as follow-up issues below.
- New failure-parity obligation: the archive intake path is a new upload
  surface and must be added to
  `services/inh-public-api-svc/tests/contract/test_failure_parity.py`
  (CLAUDE.md dual-surface rule) — though its only surface is REST, so parity
  here means "the archive path's own failure branches (limit-exceeded,
  S3-down, MQ-down per member) leave the same state/response pairing
  `intake_document`'s existing branches already guarantee," not a
  REST/MCP comparison.
- Operators get a bounded, auditable answer to "why didn't file X in my ZIP
  show up": `skipped_members` names it and says why, and a `partial` archive
  status makes a member-level failure visible without forcing a re-upload of
  the whole bundle.
- **Revisit when:** a real caller needs nested archives, needs MCP-surfaced
  archive upload, or member counts/sizes routinely approach the v1 limits —
  each is a scoped follow-up against this ADR's decisions, not a reason to
  reopen the fan-out/dedup/fencing model itself.

## Follow-up issues

- #186 — `archive_uploads` table + `processed_documents.parent_archive_id` migration.
- #187 — `FILE_TYPE_REGISTRY` container support (`zip` entry) + member classification helper.
- #188 — `POST /v1/archives`: intake, limits, member fan-out through `intake_document`.
- #189 — `GET /v1/archives/{archive_id}`: derived status rollup.
