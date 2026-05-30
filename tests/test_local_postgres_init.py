from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_initial_schema_does_not_require_ingestion_user_role() -> None:
    migration = (
        REPO_ROOT
        / "services"
        / "inh-ingestion-svc"
        / "scripts"
        / "migrations"
        / "000_initial_schema.sql"
    ).read_text()

    assert "to_regrole('ingestion_user')" in migration
    assert "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ingestion_user;" in migration
    assert "IF to_regrole('ingestion_user') IS NOT NULL THEN" in migration


def test_postgres_init_stops_on_migration_error() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    assert "set -e" in compose
    assert "psql -h postgres" in compose
    assert "-v ON_ERROR_STOP=1" in compose
