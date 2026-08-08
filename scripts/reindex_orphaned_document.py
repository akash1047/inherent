#!/usr/bin/env python3
"""Operator entry point: reindex a document straight from its stored Postgres
chunks into Weaviate (#221).

Fixes the case ``scripts/check_index_consistency.py`` flags: a document with
``status: processed`` and real, verified-good chunk text in
``document_chunks``, but zero objects in the vector index — so it never
appears in search. Does NOT re-fetch, re-extract, or re-chunk the source
file (unlike ``refresh_stale_source`` / ``POST /v1/documents/{id}/refresh`` —
see ``services/inh-ingestion-svc/src/services/reindex_from_postgres.py`` for
why that path doesn't fit a document with an unverifiable ``storage_path``).
It only reads the chunks exactly as they exist today and writes their
embeddings to Weaviate.

Run from the repository root:

    uv --project services/inh-ingestion-svc run python \\
        scripts/reindex_orphaned_document.py --document-id doc_abc123

    # Multiple documents in one run (repeatable flag):
    uv --project services/inh-ingestion-svc run python \\
        scripts/reindex_orphaned_document.py \\
        --document-id doc_abc123 --document-id doc_def456

Exit code is 1 if any document was skipped or failed to reindex, 0 if every
requested document now has vectors in Weaviate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INGESTION_SVC = REPO_ROOT / "services" / "inh-ingestion-svc"


def _load_repo_env() -> None:
    """Load ``REPO_ROOT/.env`` into ``os.environ`` before constructing Settings.

    Mirrors ``scripts/validate_env.py`` / ``scripts/check_index_consistency.py``
    — same python-dotenv-first, minimal-parser-fallback approach, kept
    consistent across all three operator scripts.
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


async def _main(args: argparse.Namespace) -> int:
    _load_repo_env()
    sys.path.insert(0, str(INGESTION_SVC))

    from src.config.settings import get_settings
    from src.services.database import DatabaseService
    from src.services.reindex_from_postgres import reindex_document_from_postgres
    from src.services.weaviate import WeaviateService

    settings = get_settings()

    database = DatabaseService(settings)
    database.connect()

    weaviate = WeaviateService(settings)
    weaviate.connect()

    if not weaviate.is_connected():
        print(
            "ERROR: could not connect to Weaviate — aborting before touching any document."
        )
        return 1

    failures = 0
    try:
        for document_id in args.document_id:
            result = await reindex_document_from_postgres(
                database=database, weaviate=weaviate, document_id=document_id
            )
            if result.skipped:
                print(f"SKIPPED {document_id}: {result.reason}")
                failures += 1
            else:
                print(
                    f"OK {document_id}: embedded {result.chunks_embedded} chunk(s) into Weaviate"
                )
    finally:
        weaviate.disconnect()
        database.disconnect()

    return 1 if failures else 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-id",
        action="append",
        required=True,
        metavar="DOCUMENT_ID",
        help="Document to reindex from its stored Postgres chunks. Repeatable.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_parse_args())))
