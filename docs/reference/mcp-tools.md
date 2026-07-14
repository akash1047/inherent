# MCP tools reference

The public API service ships an MCP server (`inherent-knowledge-base`)
exposing the same capabilities as the REST API with matching permission
enforcement and failure behavior.

## Running & transport

- **Transport: stdio.** Start the service with `SERVICE_MODE=mcp`; the MCP
  server runs as its own process (it is not mounted on the REST app).
- Every tool call carries the API key as a schema argument (`api_key`) —
  there are no transport headers on stdio. The key is validated and the
  tool's permission checked **before** the handler runs, mirroring REST
  401/403 behavior. Handlers additionally enforce workspace ownership.
- Tools, schemas, permissions, and dispatch all derive from a single
  `_TOOLS` registry entry per tool, so the advertised surface cannot drift
  from the enforced one.

## Tools

All tools require `api_key` (string). Additional parameters below.

### Search (`search` permission)

| Tool | Parameters | Purpose | REST twin |
| --- | --- | --- | --- |
| `search_documents` | `query` (required); `workspace_id`, `limit` (10), `min_score` (0.0), `document_ids[]`, `search_mode` (`semantic`/`hybrid`/`keyword`), `alpha` (0.7) | Search chunks; fans out across all owned workspaces when none given | `POST /v1/search` |
| `search_memory` | same as `search_documents` | Memory-primitive alias — identical behavior | `POST /v1/search` |
| `get_citations` | same as `search_documents` | Search returning claim-level citation objects (spans, score, provenance, freshness) | `POST /v1/search` |
| `report_feedback` | `event_id`, `verdict` (`answered`/`partial`/`not_relevant`) required; `useful_chunk_ids[]`, `note` | Record a verdict on a captured search event; builds the workspace eval set | `POST /v1/evals/feedback` |
| `get_retrieval_health` | `workspace_id` (required) | Workspace retrieval scorecard | `GET /v1/evals/scorecard` |

### Read (`read` permission)

| Tool | Parameters | Purpose | REST twin |
| --- | --- | --- | --- |
| `list_documents` | `workspace_id`, `page` (1), `page_size` (20) | Paginated document listing | `GET /v1/documents` |
| `get_document` | `document_id` (required) | Single document's metadata | `GET /v1/documents/{id}` |
| `list_chunks` | `document_id` (required) | All chunks for a document | `GET /v1/chunks/{document_id}` |
| `get_document_context` | `document_id` (required) | Full concatenated chunk text + metadata header | `GET /v1/chunks/{document_id}/context` |
| `verify_claim` | `claim` (required); `evidence[]` | Offline lexical claim-vs-evidence support scoring | `POST /v1/verify-claim` |
| `explain_lineage` | `document_id` (required); `chunk_id` | Provenance + freshness for a document or chunk | `GET /v1/documents/{id}/lineage` |

### Write (`write` permission)

| Tool | Parameters | Purpose | REST twin |
| --- | --- | --- | --- |
| `upload_document` | `filename`, `content` (required); `content_type` (`text/markdown` default — `text/plain`, `text/csv`, `text/html` accepted), `workspace_id` | **Text-only** ingestion sharing REST's validate/dedup/store/enqueue pipeline. Binary formats (PDF/DOCX/PNG) are REST-only — use `POST /v1/documents`. If the key owns several workspaces, `workspace_id` is required | `POST /v1/documents` |
| `delete_document` | `document_id` (required) | Permanently delete document + vectors + chunks + stored bytes | `DELETE /v1/documents/{id}` |
| `refresh_stale_source` | `document_id` (required) | Re-enqueue an uploaded document to clear staleness; on MQ failure a retried best-effort compensation marks it `failed`, matching REST (see the REST reference for exhaustion behavior) | `POST /v1/documents/{id}/refresh` |

## Notes

- Search tools do not take `include_context` / `context_window` — use
  `get_document_context` for surrounding text.
- Permissions are exact membership, same as REST: `write` does not imply
  `read` or `search`.
