# Inherent — Request Examples

Ready-to-run curl snippets for every API endpoint. Use these to verify the stack after `docker compose up --build`, reproduce bugs, or explore the API.

## Prerequisites

- Stack running locally (`docker compose up --build`)
- [`jq`](https://jqlang.github.io/jq/) installed (used to pretty-print responses in all snippets)

Verify stack is up:

```bash
curl http://localhost:18000/health
curl http://localhost:18002/health
```

## Bootstrap: Create a Dev API Key

The database ships with no seed keys. API keys **must start with `ink_`** — any other prefix is rejected immediately.

Run once after `docker compose up --build`:

```bash
make dev-seed
```

Safe to re-run — skips if key already exists. Expected output: `Done. API key ready: ink_dev_local_key_001`

## Variables

All examples use these shell variables. Set them once:

```bash
export API_BASE="http://localhost:18000"
export INGEST_BASE="http://localhost:18002"
export API_KEY="ink_dev_local_key_001"  # created by make dev-seed
export WORKSPACE_ID="ws_local_001"      # matches workspace seeded above
export INGEST_KEY="dev-ingestion-key"   # set via INGESTION_API_KEY in docker-compose
```

---

## 1. Health

### Liveness (public API)

```bash
curl -s "$API_BASE/health" | jq .
```

**Expected response:**

```json
{
  "status": "healthy",
  "service": "inh-public-api-svc"
}
```

### Readiness (public API — checks PostgreSQL + Weaviate)

```bash
curl -s "$API_BASE/health/ready" | jq .
```

**Expected response:**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:00:00.000000+00:00",
  "version": "0.1.0",
  "service": "inh-public-api-svc",
  "checks": {
    "database": { "status": "healthy", "latency_ms": 4.2 },
    "weaviate":  { "status": "healthy", "latency_ms": 12.7 }
  }
}
```

**Degraded example** (Weaviate slow but database OK):

```json
{
  "status": "degraded",
  "checks": {
    "database": { "status": "healthy",  "latency_ms": 3.1 },
    "weaviate":  { "status": "degraded", "latency_ms": 612.0, "message": "High latency detected" }
  }
}
```

### Liveness (ingestion API)

```bash
curl -s "$INGEST_BASE/health" | jq .
```

---

## 2. Upload a Document

Allowed MIME types: `text/plain`, `text/markdown`, `text/csv`, `text/html`,
`application/pdf`, `application/json`,
`application/vnd.openxmlformats-officedocument.wordprocessingml.document`.
Max size: 50 MB.

### Upload plain text

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.txt;type=text/plain" \
  | jq .
```

### Upload Markdown

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.md;type=text/markdown" \
  | jq .
```

### Upload JSON

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.json;type=application/json" \
  | jq .
```

### Upload CSV

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.csv;type=text/csv" \
  | jq .
```

### Upload HTML

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.html;type=text/html" \
  | jq .
```

### Upload PDF

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.pdf;type=application/pdf" \
  | jq .
```

### Upload DOCX

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  | jq .
```

**Expected response (201):**

```json
{
  "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "sample.txt",
  "workspace_id": "ws_local_001",
  "storage_url": "s3://inherent-documents/ws_local_001/3fa85f64-5717-4562-b3fc-2c963f66afa6/sample.txt",
  "mime_type": "text/plain",
  "size_bytes": 842,
  "status": "pending",
  "message": "Document uploaded successfully. Processing will begin shortly."
}
```

Save the document ID for later examples:

```bash
export DOC_ID="3fa85f64-5717-4562-b3fc-2c963f66afa6"  # replace with your value
```

### Upload error cases

**Unsupported file type (400):**

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@/etc/hosts;type=application/octet-stream" \
  | jq .
```

```json
{
  "type": "https://api.inherent.systems/errors/bad-request",
  "title": "Bad Request",
  "status": 400,
  "detail": "Unsupported file type 'application/octet-stream'. Allowed types: text/plain, text/markdown, text/csv, text/html, application/pdf, application/json, application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
```

**Missing API key (401):**

```bash
curl -s -X POST "$API_BASE/v1/documents" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -F "file=@docs/examples/sample-documents/sample.txt;type=text/plain" \
  | jq .
```

```json
{
  "detail": "API key required. Provide X-API-Key header or Authorization: Bearer <key>"
}
```

---

## 3. List Documents

```bash
curl -s "$API_BASE/v1/documents" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

### With pagination

```bash
curl -s "$API_BASE/v1/documents?page=1&page_size=5" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

**Expected response:**

```json
{
  "documents": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "name": "sample.txt",
      "workspace_id": "ws_local_001",
      "source_type": "upload",
      "mime_type": "text/plain",
      "size_bytes": 842,
      "chunk_count": 4,
      "status": "processed",
      "created_at": "2024-01-15T10:00:00+00:00",
      "updated_at": "2024-01-15T10:00:05+00:00",
      "metadata": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 5
}
```

---

## 4. Get Document by ID

```bash
curl -s "$API_BASE/v1/documents/$DOC_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

**Expected response:**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "sample.txt",
  "workspace_id": "ws_local_001",
  "source_type": "upload",
  "mime_type": "text/plain",
  "size_bytes": 842,
  "chunk_count": 4,
  "status": "processed",
  "created_at": "2024-01-15T10:00:00+00:00",
  "updated_at": "2024-01-15T10:00:05+00:00",
  "metadata": null
}
```

**Document not found (404):**

```bash
curl -s "$API_BASE/v1/documents/does-not-exist" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

```json
{
  "detail": "Document not found"
}
```

---

## 5. Search

Wait for ingestion to complete (`status: "processed"` in list/get) before searching.

### Semantic search (default)

```bash
curl -s -X POST "$API_BASE/v1/search" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "what retrieval modes does Inherent support",
    "limit": 5
  }' \
  | jq .
```

### Hybrid search

```bash
curl -s -X POST "$API_BASE/v1/search" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "document ingestion pipeline",
    "limit": 5,
    "search_mode": "hybrid",
    "alpha": 0.6
  }' \
  | jq .
```

### Keyword search

```bash
curl -s -X POST "$API_BASE/v1/search" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Weaviate PostgreSQL",
    "limit": 5,
    "search_mode": "keyword"
  }' \
  | jq .
```

### Search with context window

Includes surrounding chunks for each result — useful for MCP-style context retrieval.

```bash
curl -s -X POST "$API_BASE/v1/search" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "supported file formats",
    "limit": 3,
    "include_context": true,
    "context_window": 2
  }' \
  | jq .
```

### Search filtered to specific documents

```bash
curl -s -X POST "$API_BASE/v1/search" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"embeddings\",
    \"limit\": 5,
    \"document_ids\": [\"$DOC_ID\"]
  }" \
  | jq .
```

**Expected response:**

```json
{
  "results": [
    {
      "chunk_id": "chunk-uuid-here",
      "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "document_name": "sample.txt",
      "content": "Section 2: Key Concepts\nInherent is a backend system...",
      "score": 0.87,
      "metadata": {
        "chunk_index": 1,
        "token_count": 64
      },
      "context_before": null,
      "context_after": null
    }
  ],
  "query": "what retrieval modes does Inherent support",
  "total_results": 1,
  "processing_time_ms": 42.3,
  "search_mode": "semantic",
  "total_tokens": 0
}
```

**Empty results (no matching documents):**

```json
{
  "results": [],
  "query": "xyzzy nonexistent term",
  "total_results": 0,
  "processing_time_ms": 18.1,
  "search_mode": "semantic",
  "total_tokens": 0
}
```

---

## 6. Fetch Chunks

### List all chunks for a document

```bash
curl -s "$API_BASE/v1/chunks/$DOC_ID" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

**Expected response:**

```json
[
  {
    "id": "1",
    "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "content": "Inherent Knowledge Base — Sample Text Document\n\nThis is a plain text file...",
    "chunk_index": 0,
    "token_count": 141,
    "metadata": null
  }
]
```

### Get document context (all chunks as full text)

Returns metadata + all chunks combined into `full_text`. Use this for MCP-style full-document context retrieval.

```bash
curl -s "$API_BASE/v1/chunks/$DOC_ID/context" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Workspace-Id: $WORKSPACE_ID" \
  | jq .
```

**Expected response:**

```json
{
  "document": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "sample.txt",
    "workspace_id": "ws_local_001",
    "source_type": "upload",
    "mime_type": "text/plain",
    "size_bytes": 842,
    "chunk_count": 4,
    "status": "processed",
    "created_at": "2024-01-15T10:00:00+00:00",
    "updated_at": "2024-01-15T10:00:05+00:00",
    "metadata": null
  },
  "chunks": [
    {
      "id": "1",
      "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "content": "Inherent Knowledge Base — Sample Text Document...",
      "chunk_index": 0,
      "token_count": 141,
      "metadata": null
    }
  ],
  "full_text": "Inherent Knowledge Base — Sample Text Document\n\n...\n\nSection 4: Retrieval Modes\n..."
}
```

---

## 7. Trigger Ingestion Manually

Use when you need to re-ingest a file already in S3 without going through the upload endpoint.

```bash
curl -s -X POST "$INGEST_BASE/ingest" \
  -H "X-API-Key: $INGEST_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"document_id\": \"$DOC_ID\",
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"user_id\": \"user_local_001\",
    \"filename\": \"sample.txt\",
    \"original_filename\": \"sample.txt\",
    \"content_type\": \"text/plain\",
    \"size_bytes\": 842,
    \"storage_backend\": \"s3\",
    \"storage_path\": \"$WORKSPACE_ID/$DOC_ID/sample.txt\"
  }" \
  | jq .
```

---

## 8. Common Error Reference

| HTTP Status | Cause | Fix |
|---|---|---|
| 400 | Unsupported MIME type | Use an allowed type (see Upload section) |
| 400 | Empty file | Upload a non-empty file |
| 400 | File exceeds 50 MB | Split or compress the file |
| 400 | Missing workspace ID | Add `X-Workspace-Id` header |
| 401 | Missing or invalid API key | Set `X-API-Key` header |
| 403 | Key lacks required permission | Use a key with write/read/search permission |
| 404 | Document not found | Check document ID and workspace |
| 429 | Rate limit exceeded | Wait and retry; check `Retry-After` header |
| 503 | Backing service unavailable | Check `GET /health/ready` for which component is down |

---

## Sample Files

| File | MIME Type | Located at |
|---|---|---|
| `sample.txt` | `text/plain` | `docs/examples/sample-documents/sample.txt` |
| `sample.md` | `text/markdown` | `docs/examples/sample-documents/sample.md` |
| `sample.json` | `application/json` | `docs/examples/sample-documents/sample.json` |
| `sample.csv` | `text/csv` | `docs/examples/sample-documents/sample.csv` |
| `sample.html` | `text/html` | `docs/examples/sample-documents/sample.html` |
| `sample.pdf` | `application/pdf` | Generate with any PDF tool; not committed (binary) |
| `sample.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | Generate with LibreOffice/Word; not committed (binary) |

### Generate sample PDF (requires `enscript` + `ps2pdf`)

```bash
enscript -p /tmp/sample.ps docs/examples/sample-documents/sample.txt
ps2pdf /tmp/sample.ps docs/examples/sample-documents/sample.pdf
```

### Generate sample DOCX (requires LibreOffice)

```bash
libreoffice --headless --convert-to docx \
  docs/examples/sample-documents/sample.txt \
  --outdir docs/examples/sample-documents/
```
