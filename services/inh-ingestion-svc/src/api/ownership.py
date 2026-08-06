"""Workspace-ownership checks shared by inh-ingestion-svc's protected routes.

Every route in ``src/api/app.py`` is gated by ``Depends(verify_api_key)`` --
proof the caller holds the ONE shared ``INGESTION_API_KEY`` service secret,
not proof the caller is entitled to touch a particular workspace's data.
Unlike the public API's per-key workspace entitlement model
(``resolve_workspace_read`` in inh-public-api-svc), ``verify_api_key`` has no
key->workspace binding at all (#177) -- closing that gap is a bigger,
separate design decision (see #177's issue body). Until it lands, every
route that takes a ``document_id`` or dead-letter ``job_id`` and a caller-
supplied ``workspace_id`` MUST verify the two are actually paired in
PostgreSQL before doing anything else with them -- the "match-or-404" shape
#134 established for ``PATCH /chunks/{document_id}/{chunk_index}``. This
module gives every other route (#134's own follow-ups: #175's
``DELETE /documents``, #177's six read/write routes) one place to call that
check from instead of re-deriving it per endpoint.

This is workspace<->row CONSISTENCY, not caller<->workspace ENTITLEMENT --
narrower than it looks at a glance. A caller that already knows a genuine
``(document_id, workspace_id)`` pair for a workspace it doesn't own (e.g. by
reading one out of an unscoped ``GET /dead-letter``) still passes these
checks; #177 closes that specific escalation path by making ``GET
/dead-letter`` require and enforce ``workspace_id`` instead of treating it as
an optional filter, and by applying this same match-or-404 guard to the
single-job dead-letter routes so a job can't be read/mutated by guessing an
id, either.

Both helpers below are deliberately thin wrappers with NO try/except: a
PostgreSQL failure during the ownership lookup must propagate as a 5xx, never
be silently swallowed into an "allow" decision. This mirrors the posture of
``services/inh-public-api-svc/src/services/database.py::user_owns_workspace_in_mongo``,
which raises on failure for the identical reason -- see that method's
docstring, and docs/developer/learnings.md, for why fail-open on an
authorization lookup is unacceptable even during an outage.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


async def resolve_owned_document(
    db_svc: Any, document_id: str, workspace_id: str
) -> dict[str, Any]:
    """Resolve ``document_id`` in PostgreSQL and verify ``workspace_id`` owns it.

    Same response for "no such document" and "exists in a workspace you
    don't own" -- a distinguishable error would leak cross-tenant existence
    of ``document_id``. Used by #175 (``DELETE /documents/{document_id}``),
    #177's ``GET /ingest/{document_id}/status`` and ``GET
    /lineage/{document_id}``, and (already, pre-existing) #134's
    ``PATCH /chunks/{document_id}/{chunk_index}``.

    Args:
        db_svc: A ``DatabaseService`` (or test double) exposing
            ``get_document_status``.
        document_id: The document to resolve.
        workspace_id: The workspace the caller claims owns it.

    Returns:
        The full ``processed_documents`` row as a dict.

    Raises:
        HTTPException: 404 if the document doesn't exist, or exists but its
            stored ``workspace_id`` doesn't match.
        Exception: whatever ``db_svc.get_document_status`` itself raises
            (e.g. a DB outage) -- deliberately NOT caught here. See the
            module docstring.
    """
    document = await db_svc.get_document_status(document_id)
    if document is None or document.get("workspace_id") != workspace_id:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found in workspace {workspace_id}.",
        )
    return document


async def resolve_owned_dead_letter_job(
    db_svc: Any, job_id: int, workspace_id: str
) -> dict[str, Any]:
    """Resolve dead-letter ``job_id`` and verify ``workspace_id`` owns it.

    Same match-or-404 shape as ``resolve_owned_document``, applied to
    ``dead_letter_jobs`` rows (#177: ``GET /dead-letter/{job_id}``, ``POST
    /dead-letter/{job_id}/retry``, ``POST /dead-letter/{job_id}/abandon``).
    ``dead_letter_jobs.workspace_id`` is ``NOT NULL`` (see
    ``DatabaseService._define_tables``), so there is no "row exists but has
    no workspace_id" case to special-case here.

    Args:
        db_svc: A ``DatabaseService`` (or test double) exposing
            ``get_dead_letter_job``.
        job_id: The dead-letter job to resolve.
        workspace_id: The workspace the caller claims owns it.

    Returns:
        The full ``dead_letter_jobs`` row as a dict.

    Raises:
        HTTPException: 404 if the job doesn't exist, or exists but its
            stored ``workspace_id`` doesn't match.
        Exception: whatever ``db_svc.get_dead_letter_job`` itself raises --
            deliberately NOT caught here. See the module docstring.
    """
    job = await db_svc.get_dead_letter_job(job_id)
    if job is None or job.get("workspace_id") != workspace_id:
        raise HTTPException(
            status_code=404,
            detail=f"Dead-letter job {job_id} not found in workspace {workspace_id}.",
        )
    return job
