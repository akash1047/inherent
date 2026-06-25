"""Unit tests for the in-image SQL migration runner (SERVICE_MODE=migrate).

These are pure/offline: the psycopg2 DBAPI connection is faked, so no real
PostgreSQL is needed. They pin the orchestration contract that mirrors the
Compose ``postgres-init`` shell loop:
  - tracking table is ensured first
  - a pre-tracking DB (schema present, tracking empty) is BACKFILLED, never
    re-applied (the #16 non-destructive guarantee)
  - on a fresh DB every ``*.sql`` is applied once, in filename order
  - already-applied migrations are skipped (idempotent re-run)

The real SQL execution against Postgres is covered by an end-to-end check
(build image -> SERVICE_MODE=migrate -> verify schema + idempotent re-run).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services import migrations


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """No-op override of the package-level DB-dependent autouse fixture.

    The package ``tests/conftest.py`` defines an autouse ``cleanup_test_data``
    that depends on ``db_service`` and skips when PostgreSQL is unavailable.
    These tests are pure/offline, so we override it with a no-op.
    """
    yield


class FakeCursor:
    """Records executed SQL and answers fetchone() based on the query text.

    ``applied`` is the set of migration filenames the fake DB already has in
    ``_migrations``; ``schema_present`` toggles the to_regclass probe.
    """

    def __init__(self, state):
        self.state = state

    def execute(self, sql, params=None):
        self.state["executed"].append((sql, params))
        self._last = (sql, params)
        # Model the DB state change: any INSERT into _migrations (backfill or
        # apply) makes that filename "already applied" for later probes — so a
        # backfilled row is not re-applied, matching real Postgres.
        if sql.startswith("INSERT INTO _migrations (filename)") and params:
            self.state["applied"].add(params[0])

    def fetchone(self):
        sql, params = self._last
        if "to_regclass" in sql:
            return (self.state["schema_present"],)
        if "COUNT(*) FROM _migrations" in sql:
            return (len(self.state["applied"]),)
        if "SELECT 1 FROM _migrations WHERE filename" in sql:
            return (1,) if params[0] in self.state["applied"] else None
        return None

    def close(self):
        pass


class FakeRawConn:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return FakeCursor(self.state)

    def commit(self):
        self.state["commits"] += 1

    def rollback(self):
        self.state["rollbacks"] += 1

    def close(self):
        pass


class FakeEngine:
    def __init__(self, state):
        self.state = state

    def raw_connection(self):
        return FakeRawConn(self.state)

    def dispose(self):
        self.state["disposed"] = True


def _patch_engine(monkeypatch, state):
    monkeypatch.setattr(migrations, "create_engine", lambda *a, **k: FakeEngine(state))


def _make_migrations(tmp_path, names):
    for n in names:
        (tmp_path / n).write_text(f"-- {n}\nSELECT 1;\n")
    # A non-.sql file must be ignored (the glob is *.sql, like `*.sql` in psql).
    (tmp_path / "README.md").write_text("not a migration")


def _applied_files(state):
    """Filenames passed to INSERT INTO _migrations (the ones actually applied)."""
    return [
        params[0]
        for sql, params in state["executed"]
        if sql.startswith("INSERT INTO _migrations (filename) VALUES (%s);")
    ]


def _settings():
    return SimpleNamespace(database_url="postgresql://u:p@h:5432/db")


def test_fresh_db_applies_all_in_order(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path))
    _make_migrations(tmp_path, ["000_a.sql", "001_b.sql", "002_c.sql"])
    state = {
        "executed": [],
        "applied": set(),
        "schema_present": False,
        "commits": 0,
        "rollbacks": 0,
    }
    _patch_engine(monkeypatch, state)

    migrations.run_migrations(_settings())

    assert _applied_files(state) == ["000_a.sql", "001_b.sql", "002_c.sql"]
    assert state["rollbacks"] == 0
    assert state["disposed"] is True


def test_already_applied_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path))
    _make_migrations(tmp_path, ["000_a.sql", "001_b.sql"])
    state = {
        "executed": [],
        "applied": {"000_a.sql", "001_b.sql"},
        "schema_present": True,  # tracking non-empty => no backfill branch
        "commits": 0,
        "rollbacks": 0,
    }
    _patch_engine(monkeypatch, state)

    migrations.run_migrations(_settings())

    # Nothing re-applied.
    assert _applied_files(state) == []


def test_pretracking_db_backfills_without_rerunning(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path))
    _make_migrations(tmp_path, ["000_a.sql", "001_b.sql"])
    # Schema exists but tracking is empty: the old blind-loop provisioning.
    state = {
        "executed": [],
        "applied": set(),
        "schema_present": True,
        "commits": 0,
        "rollbacks": 0,
    }
    _patch_engine(monkeypatch, state)

    migrations.run_migrations(_settings())

    # Backfill uses ON CONFLICT DO NOTHING inserts, NOT the plain apply insert,
    # so no destructive migration SQL is re-run.
    backfilled = [
        params[0] for sql, params in state["executed"] if "ON CONFLICT (filename) DO NOTHING" in sql
    ]
    assert backfilled == ["000_a.sql", "001_b.sql"]
    # The apply path still runs but every file now reads as applied -> skipped.
    assert _applied_files(state) == []


def test_missing_directory_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path / "does-not-exist"))
    with pytest.raises(RuntimeError, match="Migrations directory not found"):
        migrations.run_migrations(_settings())


def test_empty_directory_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MIGRATIONS_DIR", str(tmp_path))
    (tmp_path / "README.md").write_text("no sql here")
    with pytest.raises(RuntimeError, match="No \\*.sql migrations found"):
        migrations.run_migrations(_settings())
