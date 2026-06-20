#!/usr/bin/env bash
#
# Local OSS bootstrap (#5).
#
# Creates the records a fresh local stack needs before any protected public-API
# call works, in BOTH control-plane stores the auth flow reads:
#   1. PostgreSQL  api_keys  row  (key validation)
#   2. MongoDB     workspaces doc (workspace-ownership resolution)
#
# Idempotent: safe to re-run. Uses ON CONFLICT / upsert.
#
# !! LOCAL / DEV ONLY !!
# The key value is a well-known development placeholder. Never run this against
# a production database and never reuse this key outside local development.
#
# Configurable via environment (defaults match the Makefile):
#   API_KEY, WORKSPACE_ID, USER_ID, KEY_NAME
#   PG_CONTAINER, PG_USER, PG_DB
#   MONGO_CONTAINER, MONGO_DB
set -euo pipefail

API_KEY="${API_KEY:-ink_dev_local_key_001}"
WORKSPACE_ID="${WORKSPACE_ID:-ws_local_001}"
USER_ID="${USER_ID:-local-dev-user}"
KEY_NAME="${KEY_NAME:-Local Dev Key}"
WORKSPACE_NAME="${WORKSPACE_NAME:-Local Dev Workspace}"

PG_CONTAINER="${PG_CONTAINER:-inherent-oss-postgres}"
PG_USER="${PG_USER:-postgres}"
PG_DB="${PG_DB:-knowledge_base}"

MONGO_CONTAINER="${MONGO_CONTAINER:-inherent-oss-mongodb}"
MONGO_DB="${MONGO_DB:-main}"

if [[ "$API_KEY" != ink_* ]]; then
  echo "Error: API_KEY must start with 'ink_' (public API rejects other prefixes)." >&2
  exit 1
fi

container_running() {
  docker ps --format '{{.Names}}' | grep -qx "$1"
}

for c in "$PG_CONTAINER" "$MONGO_CONTAINER"; do
  if ! container_running "$c"; then
    echo "Error: container '$c' is not running. Start the stack first (e.g. 'make dev')." >&2
    exit 1
  fi
done

echo "Bootstrapping local dev workspace + API key (LOCAL/DEV ONLY)..."

# 1. PostgreSQL api_keys row. key_hash is sha256(hex) of the full key; key_prefix
#    is the first 12 chars (matches services validation).
echo "  - PostgreSQL api_keys ($PG_DB) ..."
docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" -c \
  "INSERT INTO api_keys
     (key_id, key_hash, key_prefix, user_id, workspace_id, name, status, permissions, rate_limit)
   VALUES (
     gen_random_uuid()::text,
     encode(sha256('${API_KEY}'::bytea), 'hex'),
     left('${API_KEY}', 12),
     '${USER_ID}',
     '${WORKSPACE_ID}',
     '${KEY_NAME}',
     'active',
     '[\"read\",\"write\",\"search\"]',
     1000
   )
   ON CONFLICT (key_hash) DO UPDATE
     SET status = 'active',
         user_id = EXCLUDED.user_id,
         workspace_id = EXCLUDED.workspace_id,
         permissions = EXCLUDED.permissions;" >/dev/null

# 2. MongoDB workspaces doc. Ownership lookup matches on user_id and returns
#    str(_id) as the workspace id, so _id must equal WORKSPACE_ID.
echo "  - MongoDB workspaces ($MONGO_DB) ..."
docker exec -i "$MONGO_CONTAINER" mongosh --quiet "$MONGO_DB" --eval \
  "db.workspaces.updateOne(
     { _id: '${WORKSPACE_ID}' },
     { \$set: { user_id: '${USER_ID}', name: '${WORKSPACE_NAME}' } },
     { upsert: true }
   )" >/dev/null

cat <<EOF

Bootstrap complete (local/dev only). Use these for local API calls:

  API key       : ${API_KEY}
  Workspace ID  : ${WORKSPACE_ID}
  User ID       : ${USER_ID}

Example:
  curl -s http://localhost:18000/v1/search \\
    -H "X-API-Key: ${API_KEY}" \\
    -H "X-Workspace-Id: ${WORKSPACE_ID}" \\
    -H "Content-Type: application/json" \\
    -d '{"query":"hello","limit":3}'
EOF
