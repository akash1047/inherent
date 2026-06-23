#!/bin/bash

# Create multiple workspaces for separate test scenarios
# Adds two workspaces to PostgreSQL and MongoDB using proper key hashing

set -e

PG_CONTAINER="inherent-oss-postgres"
PG_USER="postgres"
PG_DB="knowledge_base"
MONGO_CONTAINER="inherent-oss-mongodb"
MONGO_DB="main"

echo "==> Creating separate workspaces for test scenarios..."
echo ""

# Workspace 1: Test with 3 unique documents
WS1_ID="ws_search_flood_test_3"
WS1_NAME="Search Flood Test - 3 Unique"
WS1_USER="test-user-3"
WS1_KEY="ink_test_3_unique_key"

# Workspace 2: Test with 5 documents (3 unique + 2 duplicates)
WS2_ID="ws_search_flood_test_5"
WS2_NAME="Search Flood Test - 5 with Dupes"
WS2_USER="test-user-5"
WS2_KEY="ink_test_5_dupes_key"

# Create Workspace 1
echo "Creating Workspace 1: $WS1_ID"
docker exec "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" -c "
  INSERT INTO api_keys
    (key_id, key_hash, key_prefix, user_id, workspace_id, name, status, permissions, rate_limit)
  VALUES (
    gen_random_uuid()::text,
    encode(sha256('${WS1_KEY}'::bytea), 'hex'),
    left('${WS1_KEY}', 12),
    '${WS1_USER}',
    '${WS1_ID}',
    '${WS1_NAME}',
    'active',
    '[\"read\",\"write\",\"search\"]',
    1000
  )
  ON CONFLICT (key_hash) DO UPDATE
    SET status = 'active',
        user_id = EXCLUDED.user_id,
        workspace_id = EXCLUDED.workspace_id;" >/dev/null

docker exec "$MONGO_CONTAINER" mongosh --quiet "$MONGO_DB" --eval "
  db.workspaces.updateOne(
    { _id: '${WS1_ID}' },
    { \$set: { user_id: '${WS1_USER}', name: '${WS1_NAME}' } },
    { upsert: true }
  )
" >/dev/null

echo "  ✓ Workspace 1 created"
echo "    API Key: $WS1_KEY"
echo "    Workspace ID: $WS1_ID"
echo ""

# Create Workspace 2
echo "Creating Workspace 2: $WS2_ID"
docker exec "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" -c "
  INSERT INTO api_keys
    (key_id, key_hash, key_prefix, user_id, workspace_id, name, status, permissions, rate_limit)
  VALUES (
    gen_random_uuid()::text,
    encode(sha256('${WS2_KEY}'::bytea), 'hex'),
    left('${WS2_KEY}', 12),
    '${WS2_USER}',
    '${WS2_ID}',
    '${WS2_NAME}',
    'active',
    '[\"read\",\"write\",\"search\"]',
    1000
  )
  ON CONFLICT (key_hash) DO UPDATE
    SET status = 'active',
        user_id = EXCLUDED.user_id,
        workspace_id = EXCLUDED.workspace_id;" >/dev/null

docker exec "$MONGO_CONTAINER" mongosh --quiet "$MONGO_DB" --eval "
  db.workspaces.updateOne(
    { _id: '${WS2_ID}' },
    { \$set: { user_id: '${WS2_USER}', name: '${WS2_NAME}' } },
    { upsert: true }
  )
" >/dev/null

echo "  ✓ Workspace 2 created"
echo "    API Key: $WS2_KEY"
echo "    Workspace ID: $WS2_ID"
echo ""

echo "=========================================="
echo "Workspaces ready for testing"
echo "=========================================="