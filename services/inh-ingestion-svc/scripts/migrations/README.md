# Database migrations

PostgreSQL schema migrations for Inherent, applied in lexicographic order by
numeric prefix (`000_…`, `001_…`, …).

## How migrations are applied

There are two runners, and **both are idempotent** — each migration is applied
at most once per database:

| Runner | Used by | Tracking |
| --- | --- | --- |
| `postgres-init` service in `docker-compose.yml` | local Compose stack (`make up` / `make dev`) | `_migrations` table |
| `scripts/run_migrations.sh` | manual / remote (`DATABASE_URL=… ./run_migrations.sh`) | `_migrations` table |

Both create a `_migrations` tracking table:

```sql
CREATE TABLE IF NOT EXISTS _migrations (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

On each startup the runner walks the migration files in order and **skips any
filename already recorded** in `_migrations`, then records each one it applies.

## Fresh-start safety (#16)

- **Fresh database:** every migration runs once, in order, and is recorded.
- **Restart / `docker compose up` again:** all migrations are already recorded,
  so none re-run. This is what makes restart non-destructive — the historical
  destructive statements (`DROP TABLE` in `001_consolidated_schema.sql` and
  `007_drop_versioning.sql`) only ever execute once on the initial fresh build,
  never on a populated database.
- **Pre-tracking database** (provisioned by the old blind loop, so the schema
  exists but `_migrations` is empty): `postgres-init` detects this (schema
  present + empty tracking) and **backfills** the history records *without*
  re-running the migrations, so upgrading to the tracked runner cannot trigger a
  destructive re-apply.

## Adding a migration

1. Create a new file with the next numeric prefix (e.g. `008_<change>.sql`).
2. Make it **idempotent**: use `IF NOT EXISTS` / `IF EXISTS`,
   `CREATE OR REPLACE`, and `ON CONFLICT` so a partially-applied run can be
   re-attempted safely.
3. Prefer **additive** changes. Avoid dropping core data tables; if a column or
   table must be removed, do it in its own clearly-named migration and document
   the data implications.
4. Never edit a migration that has already shipped — its effect is recorded by
   filename and existing databases will not re-run it.
