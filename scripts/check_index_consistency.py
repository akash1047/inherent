#!/usr/bin/env python3
"""Operator entry point for the Postgres/Weaviate index-consistency check (#221).

Answers the two data questions issue #221 asks for directly from its output:

1. Which documents report ``status: processed`` with real Postgres chunks but
   have ZERO objects in their workspace's Weaviate collection/tenant (invisible
   to every search mode despite looking "ready").
2. How many of those share a suspicious backfill signature: a fixed
   ``ingested_at`` timestamp with a NULL ``content_hash`` (the two things the
   real ingestion pipeline can never leave null/duplicated — see
   ``src/services/index_consistency.py`` for why).

Scans one or more workspaces (``--workspace-id``, repeatable) or every
workspace that has at least one processed_documents row (``--all-workspaces``).

Run from the repository root (resolves ``REPO_ROOT/.env`` the same way
``scripts/validate_env.py`` does):

    uv --project services/inh-public-api-svc run python \\
        scripts/check_index_consistency.py --workspace-id ws_abc123

    uv --project services/inh-public-api-svc run python \\
        scripts/check_index_consistency.py --all-workspaces

Exit code is 1 when any orphaned document is found (so this can be wired into
a monitoring job/cron and alert on nonzero exit), 0 otherwise. Never mutates
anything — read-only against both stores.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_API_SVC = REPO_ROOT / "services" / "inh-public-api-svc"


def _load_repo_env() -> None:
    """Load ``REPO_ROOT/.env`` into ``os.environ`` before any service import.

    ``src.config.settings`` instantiates its ``Settings`` singleton at IMPORT
    time (``settings = get_settings()``), so env vars must already be in
    ``os.environ`` before that import happens. Mirrors
    ``scripts/validate_env.py::_load_dotenv`` (same python-dotenv-first,
    minimal-parser-fallback approach) so both operator scripts behave
    identically when python-dotenv isn't installed in a given service venv.
    """
    import os

    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import dotenv_values  # type: ignore[import-not-found]

        for key, value in dotenv_values(env_path).items():
            if value is not None and key not in os.environ:
                os.environ[key] = value
    except ImportError:
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


async def _all_workspace_ids(database) -> list[str]:
    """Every workspace_id with at least one processed_documents row.

    No dedicated DatabaseService method exists for this (by design the
    service's own API is always workspace-scoped by the caller's auth) — an
    operator sweep is the one legitimate cross-workspace case, so the query
    lives here rather than growing DatabaseService's public surface for a
    single script's sake. Reuses ``database.session()``, the same public
    context manager every other DatabaseService method uses.
    """
    from sqlalchemy import text

    async with database.session() as session:
        result = await session.execute(
            text(
                "SELECT DISTINCT workspace_id FROM processed_documents ORDER BY workspace_id"
            )
        )
        return [row[0] for row in result.fetchall()]


def _print_report(report) -> None:
    print(
        f"\nWorkspace {report.workspace_id}: {report.documents_checked} document(s) checked"
    )
    if not report.orphaned:
        print("  OK: no processed document is missing from the vector index.")
        return
    print(f"  FOUND {report.orphaned_count} orphaned document(s):")
    for doc in report.orphaned:
        print(
            f"    - document_id={doc.document_id!r} name={doc.name!r} "
            f"chunk_count={doc.chunk_count} ingested_at={doc.ingested_at!r} "
            f"content_hash={doc.content_hash!r}"
        )


def _print_backfill_signature_summary(all_orphaned: list) -> None:
    """Answer issue #221 question 2: how many documents share the backfill's
    fixed timestamp with a null content_hash.

    Groups every orphaned document (across all scanned workspaces) by
    ``ingested_at`` and reports any group of 2+ with ``content_hash is None``
    — the exact signature the issue describes (a backfill that stamped
    several documents with the SAME ingest time and never computed a hash).
    A single document sharing no timestamp with any other is not evidence of
    a backfill by itself and is left out of this summary (it is still listed
    above as an orphan needing reindexing).
    """
    groups: dict[str, list] = defaultdict(list)
    for doc in all_orphaned:
        if doc.content_hash is None and doc.ingested_at is not None:
            groups[doc.ingested_at].append(doc)

    shared = {ts: docs for ts, docs in groups.items() if len(docs) > 1}
    if not shared:
        print(
            "\nBackfill-signature summary: no shared timestamp+null-content_hash group found."
        )
        return

    print("\nBackfill-signature summary (issue #221 question 2):")
    for ts, docs in sorted(shared.items()):
        print(
            f"  {len(docs)} document(s) share ingested_at={ts!r} with content_hash=None:"
        )
        for doc in docs:
            print(f"    - {doc.document_id}")


async def _main(args: argparse.Namespace) -> int:
    _load_repo_env()
    sys.path.insert(0, str(PUBLIC_API_SVC))

    from src.services.database import close_database, get_database
    from src.services.index_consistency import check_workspace_index_consistency
    from src.services.search import close_search_service, get_search_service

    database = await get_database()
    search_service = await get_search_service()

    try:
        if args.all_workspaces:
            workspace_ids = await _all_workspace_ids(database)
            if not workspace_ids:
                print("No workspaces with processed documents found.")
                return 0
        else:
            workspace_ids = args.workspace_id

        all_orphaned: list = []
        for workspace_id in workspace_ids:
            report = await check_workspace_index_consistency(
                database, search_service, workspace_id
            )
            _print_report(report)
            all_orphaned.extend(report.orphaned)

        _print_backfill_signature_summary(all_orphaned)

        if all_orphaned:
            print(
                f"\nTotal: {len(all_orphaned)} orphaned document(s) across "
                f"{len(workspace_ids)} workspace(s). Reindex each with:\n"
                "  uv --project services/inh-ingestion-svc run python "
                "scripts/reindex_orphaned_document.py --document-id <id>"
            )
            return 1
        return 0
    finally:
        await close_search_service()
        await close_database()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--workspace-id",
        action="append",
        metavar="WORKSPACE_ID",
        help="Workspace to check. Repeatable for multiple workspaces.",
    )
    group.add_argument(
        "--all-workspaces",
        action="store_true",
        help="Check every workspace that has at least one processed document.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_parse_args())))
