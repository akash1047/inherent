"""Idempotent SQL migration runner.

This is the in-image equivalent of the `postgres-init` step in
``docker-compose.yml``: it applies the ``scripts/migrations/*.sql`` files
exactly once each, tracked in a ``_migrations`` table, so startup is
idempotent and non-destructive (#16). The destructive ``DROP``s in 001/007
only ever run on a fresh database, never on restart.

Baking this into the ingestion image (instead of a host-bind-mounted psql
container) is what makes ``docker-compose.release.yml`` self-contained: a user
running purely from published images has no repo checkout, so the migration
SQL must travel inside the image.

Invoked via ``SERVICE_MODE=migrate`` (see ``src/main.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from sqlalchemy import create_engine

from src.config.settings import Settings

logger = structlog.get_logger(__name__)


def _migrations_dir() -> Path:
    """Resolve the directory holding the ``*.sql`` migration files.

    Defaults to ``scripts/migrations`` relative to the service package root
    (where the Dockerfile COPYs them). Overridable via ``MIGRATIONS_DIR`` for
    tests or non-standard layouts.
    """
    override = os.environ.get("MIGRATIONS_DIR")
    if override:
        return Path(override)
    # src/services/migrations.py -> parents[2] == service package root
    return Path(__file__).resolve().parents[2] / "scripts" / "migrations"


def run_migrations(settings: Settings) -> None:
    """Apply pending SQL migrations idempotently against ``DATABASE_URL``.

    Mirrors the postgres-init shell loop:
      1. Ensure the ``_migrations`` tracking table exists.
      2. If the schema already exists but tracking is empty (a DB provisioned
         by the old blind loop), backfill history WITHOUT re-running — so the
         upgrade itself can never trigger a destructive re-apply.
      3. Apply each not-yet-applied ``*.sql`` file once, in filename order,
         recording it in ``_migrations`` within the same transaction.
    """
    migrations_dir = _migrations_dir()
    if not migrations_dir.is_dir():
        raise RuntimeError(f"Migrations directory not found: {migrations_dir}")

    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        raise RuntimeError(f"No *.sql migrations found in {migrations_dir}")

    logger.info(
        "Running migrations",
        directory=str(migrations_dir),
        count=len(sql_files),
    )

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        # Use the raw DBAPI (psycopg2) connection so SQL is sent verbatim. The
        # migrations contain literal '%' (e.g. `%ROWTYPE` in PL/pgSQL); passing
        # vars=None means psycopg2 performs no parameter interpolation, exactly
        # like `psql -f`.
        raw = engine.raw_connection()
        try:
            _ensure_tracking_table(raw)
            _backfill_if_pretracking(raw, sql_files)
            _apply_pending(raw, sql_files)
        finally:
            raw.close()
    finally:
        engine.dispose()

    logger.info("Migrations complete")


def _ensure_tracking_table(raw) -> None:
    cur = raw.cursor()
    try:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "id SERIAL PRIMARY KEY, "
            "filename VARCHAR(255) NOT NULL UNIQUE, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());"
        )
        raw.commit()
    finally:
        cur.close()


def _backfill_if_pretracking(raw, sql_files: list[Path]) -> None:
    """Backfill history for a pre-tracking DB without re-running migrations."""
    cur = raw.cursor()
    try:
        cur.execute("SELECT to_regclass('public.processed_documents') IS NOT NULL;")
        schema_present = bool(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM _migrations;")
        tracking_count = int(cur.fetchone()[0])

        if schema_present and tracking_count == 0:
            logger.warning(
                "Existing schema with empty tracking detected; backfilling "
                "history without re-running migrations."
            )
            for path in sql_files:
                cur.execute(
                    "INSERT INTO _migrations (filename) VALUES (%s) "
                    "ON CONFLICT (filename) DO NOTHING;",
                    (path.name,),
                )
            raw.commit()
    finally:
        cur.close()


def _apply_pending(raw, sql_files: list[Path]) -> None:
    for path in sql_files:
        cur = raw.cursor()
        try:
            cur.execute("SELECT 1 FROM _migrations WHERE filename = %s;", (path.name,))
            if cur.fetchone() is not None:
                logger.info("Skipping (already applied)", migration=path.name)
                continue

            logger.info("Applying migration", migration=path.name)
            sql = path.read_text()
            # vars=None -> psycopg2 sends SQL verbatim (no '%' interpolation).
            cur.execute(sql)
            cur.execute("INSERT INTO _migrations (filename) VALUES (%s);", (path.name,))
            raw.commit()
        except Exception:
            raw.rollback()
            logger.error("Migration failed", migration=path.name, exc_info=True)
            raise
        finally:
            cur.close()
