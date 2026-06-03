.DEFAULT_GOAL := help

.PHONY: help setup env install validate up dev down restart ps logs health doctor seed dev-seed check test lint format-check type-check security-check clean

COMPOSE              ?= docker compose
PUBLIC_API_URL       ?= http://localhost:18000
INGESTION_API_URL    ?= http://localhost:18002

INGESTION_DIR        ?= services/inh-ingestion-svc
PUBLIC_API_DIR       ?= services/inh-public-api-svc

PG_CONTAINER         ?= inherent-oss-postgres
PG_USER              ?= postgres
PG_DB                ?= knowledge_base

DEV_API_KEY          ?= ink_dev_local_key_001
DEV_WORKSPACE_ID     ?= ws_local_001
DEV_USER_ID          ?= local-dev-user
DEV_KEY_NAME         ?= Local Dev Key

## help: Show available targets.
help:
	@awk 'BEGIN {printf "\nInherent local development\n\nUsage:\n  make <target>\n\nTargets:\n"} /^## / {if (help == "") help = substr($$0, 4); next} /^[a-zA-Z0-9_.-]+:/ {if (help) {split($$1, target, ":"); desc = help; sub("^[^:]+: ", "", desc); printf "  %-18s %s\n", target[1], desc; help = ""}}' $(MAKEFILE_LIST)

## setup: Create .env if needed and install both service dev environments.
setup: env install

## env: Create .env from .env.example when .env is missing.
env:
	@if [ -f .env ]; then \
		echo ".env already exists"; \
	else \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
	fi

## install: Install dev dependencies for both Python services with uv.
install:
	@uv --project $(INGESTION_DIR) sync --extra dev --group dev
	@uv --project $(PUBLIC_API_DIR) sync --extra dev --group dev

## validate: Validate local environment settings across both services.
validate: env
	@uv --project $(INGESTION_DIR) run python scripts/validate_env.py

## up: Build and start the full local Docker Compose stack.
up: env
	@$(COMPOSE) up --build

## dev: Start the stack in the background and seed the local public API key.
dev: env
	@$(COMPOSE) up --build -d --wait
	@$(MAKE) seed

## down: Stop the local Docker Compose stack.
down:
	@$(COMPOSE) down

## restart: Restart the local Docker Compose stack in the background.
restart:
	@$(COMPOSE) down
	@$(COMPOSE) up --build -d

## ps: Show local Docker Compose service status.
ps:
	@$(COMPOSE) ps

## logs: Follow local Docker Compose logs. Use SVC=name to limit to one service.
logs:
	@if [ -n "$(SVC)" ]; then \
		$(COMPOSE) logs -f $(SVC); \
	else \
		$(COMPOSE) logs -f; \
	fi

## health: Check public API and ingestion API health endpoints.
health:
	@curl -fsS $(PUBLIC_API_URL)/health
	@printf "\n"
	@curl -fsS $(INGESTION_API_URL)/health
	@printf "\n"

## doctor: Check health of every local service and print triage hints on failure.
doctor:
	@bash scripts/dev/doctor.sh

## seed: Insert a local development API key into PostgreSQL.
##       Safe to re-run. Key value: ink_dev_local_key_001
seed:
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

## dev-seed: Alias for seed.
dev-seed: seed

## check: Run validation, lint, formatting, typing, security checks, and tests.
check: validate lint format-check type-check security-check test

## test: Run tests for both services.
test:
	@cd $(INGESTION_DIR) && uv run pytest
	@cd $(PUBLIC_API_DIR) && uv run pytest

## lint: Run Ruff checks for both services.
lint:
	@cd $(INGESTION_DIR) && uv run ruff check src tests
	@cd $(PUBLIC_API_DIR) && uv run ruff check src tests

## format-check: Check formatting for both services.
format-check:
	@cd $(INGESTION_DIR) && uv run black --check src tests
	@cd $(PUBLIC_API_DIR) && uv run black --check src tests

## type-check: Run mypy for services that currently enable it.
type-check:
	@cd $(PUBLIC_API_DIR) && uv run mypy src

## security-check: Run Bandit for services that currently enable it.
security-check:
	@cd $(PUBLIC_API_DIR) && uv run bandit -c pyproject.toml -r src

## clean: Stop the stack and remove local Compose volumes.
clean:
	@$(COMPOSE) down -v
