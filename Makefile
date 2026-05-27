.PHONY: dev-seed help

PG_CONTAINER ?= inherent-oss-postgres
PG_USER      ?= postgres
PG_DB        ?= knowledge_base

DEV_API_KEY      ?= ink_dev_local_key_001
DEV_WORKSPACE_ID ?= ws_local_001
DEV_USER_ID      ?= local-dev-user
DEV_KEY_NAME     ?= Local Dev Key

## dev-seed: Insert a local development API key into the database.
##           Safe to re-run — skips insert if key already exists.
##           Key value: ink_dev_local_key_001
##           Workspace: ws_local_001
dev-seed:
	@echo "Seeding dev API key into $(PG_DB)..."
	@docker exec $(PG_CONTAINER) psql -U $(PG_USER) -d $(PG_DB) -c \
		"INSERT INTO api_keys \
		  (key_id, key_hash, key_prefix, user_id, workspace_id, name, status, permissions, rate_limit) \
		VALUES ( \
		  gen_random_uuid()::text, \
		  encode(sha256('$(DEV_API_KEY)'::bytea), 'hex'), \
		  left('$(DEV_API_KEY)', 12), \
		  '$(DEV_USER_ID)', \
		  '$(DEV_WORKSPACE_ID)', \
		  '$(DEV_KEY_NAME)', \
		  'active', \
		  '[\"read\",\"write\",\"search\"]', \
		  1000 \
		) ON CONFLICT (key_hash) DO NOTHING;"
	@echo "Done. API key ready: $(DEV_API_KEY)"

## help: List available targets.
help:
	@grep -E '^## ' Makefile | sed 's/^## /  /'
