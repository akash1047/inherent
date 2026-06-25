# CLAUDE.md

Inherent — the ingestion, indexing, storage, and retrieval backend for a private RAG system ("company brain"). Sources are extracted, chunked, embedded, stored, and served over REST + MCP.

## Consult the knowledge graph first (saves tokens)

A graphify knowledge graph of this repo lives in `graphify-out/` (gitignored). **Before grepping or reading files to answer a question about how the codebase works, query the graph** — it answers most "how/where/why" questions at ~45× fewer tokens than reading source.

```bash
graphify query "how does authentication work"      # BFS — broad context
graphify query "how does search reach Weaviate" --dfs   # DFS — trace one path
graphify explain "DatabaseService"                  # one node + its neighbors
graphify path "SearchRequest" "WeaviateService"     # shortest path between two concepts
```

- Read `graphify-out/GRAPH_REPORT.md` for god nodes (core abstractions), community map, and surprising cross-file connections.
- Fall back to direct file reads only when the graph lacks the detail (it indexes structure + concepts, not every line).
- **The graph auto-refreshes after every `git pull`/merge** via a local post-merge hook (`make graphify-hooks` to install). The automatic pass is **AST-only** (deterministic parsing, no LLM) so it's safe to run on freshly-pulled content. Semantic re-extraction of doc/concept changes uses the Claude Code **agent** and is **opt-in only** — run `GRAPHIFY_ALLOW_AGENT_BYPASS=1 make graphify-refresh` on content you trust (it runs an agent with broad permissions; never enable it unattended on outside PRs). Default semantic model is **Haiku** via your Claude Code auth. Logs: `graphify-out/.refresh.log`.

## Commands

```bash
make setup          # env + install (first-time)
make up             # start full docker-compose stack
make check          # validate + lint + format-check + type-check + security-check + test
make test           # unit tests
make test-integration
make health         # check running services
make doctor         # diagnose environment
```

## Architecture

Three Python packages under `services/`:

- **`inh-ingestion-svc`** — ingestion pipeline: connectors → extract → chunk → embed → store. Uses **Temporal** workflows/activities (`src/temporal/`), Postgres, Weaviate (vector store, multi-tenant), S3-compatible object storage, and a message queue (Redis/Valkey).
- **`inh-public-api-svc`** — public REST + MCP API: search, verify/citations, documents, chunks. API-key auth with permission + workspace-isolation gates, RFC 7807 problem details, rate limiting, audit logging.
- **`inh-contracts`** — shared event schemas and the **Weaviate naming contract** (single source of truth for collection/tenant names across both services).

Infra (via `docker-compose.yml`): postgres, mongodb, weaviate, valkey, s3rver, text-embeddings-inference (TEI), temporal.

## Gotchas

- **Weaviate naming is contract-governed** — collection/tenant names must come from `inh-contracts` naming helpers, used by both services. Don't hand-format them.
- **`SERVICE_MODE`** env var (worker/standalone) is shared across both services; legacy aliases are mapped.
- **Multi-tenancy is workspace-scoped** — search and context-window access must enforce `workspace_id`/`user_id`; see the security regression tests in `inh-public-api-svc/tests/security/`.
- Migrations live in `services/inh-ingestion-svc/scripts/migrations/` (numbered SQL).
