# Search Flood: Content-Duplicate Dedup Gap

## Issue

Document dedup in `inh-public-api-svc/src/api/v1/documents.py` (upload
handler, ~line 74) keys re-upload reuse on `(workspace_id, filename)` only:

```python
existing_document_id = await database.get_document_id_by_filename(workspace_id, filename)
```

No content hash is checked. Uploading the same content under a different
filename creates a brand new `document_id`, a new set of chunks, and a new
set of embeddings — fully duplicated in storage and in the index.

## Test setup

5 markdown docs, 3 distinct topics (auth, rate limiting, error handling).
Each unique doc kept under ~550 chars (under the 1000-char `max_chunk_size`
in `inh-ingestion-svc`) so it produces exactly one chunk — this isolates
the dedup bug from an unrelated ranking artifact (see note below).
`api-authentication-guide.md` duplicated verbatim as `-copy-1.md` and
`-copy-2.md`. Two isolated workspaces/API keys to avoid cross-test
pollution. Wrapped by `Makefile`: `make reset`, `make setup`,
`make test-3`, `make test-5`. Query: `"API authentication token"`.

Note: an earlier version of this test used longer (~2000 char) docs, each
splitting into 3+ chunks. That let a single document's own chunks
monopolize all of limit=3, masking the dedup-specific bug behind a
separate ranking issue (no per-document diversification). Shrinking docs
to one chunk each isolates the effect of content-duplicate uploads.

## Results

**3 unique docs** (`test-3-unique.sh`, limit=3): exactly 1 result per
document — auth, rate-limiting, and error-handling docs each surface once.
This is the expected "healthy" baseline.

**5 docs, 2 are content-duplicates** (`test-5-with-dupes.sh`, limit=3):

```json
{
  "document_id": "9f83aaad-3c30-4f3b-9e6c-140bbbf6ade8",
  "document_name": "api-authentication-guide-copy-2.md",
  "chunk_id": "35681bcd-b835-5720-b725-363e7565b15b",
  "content_preview": "# API Authentication Guide\n\nTo authenticate requests, send an API key in the `X-API-Key` header or a"
}
{
  "document_id": "8e7e68d2-5733-4b19-afee-d87b7e2c92f8",
  "document_name": "api-authentication-guide-copy-1.md",
  "chunk_id": "ca140805-2d1d-525b-ac53-6be15716e91a",
  "content_preview": "# API Authentication Guide\n\nTo authenticate requests, send an API key in the `X-API-Key` header or a"
}
{
  "document_id": "b653d782-858c-4b77-8201-c00f2f443173",
  "document_name": "api-authentication-guide.md",
  "chunk_id": "0dc835c5-415e-5a9f-8068-816de3bd6025",
  "content_preview": "# API Authentication Guide\n\nTo authenticate requests, send an API key in the `X-API-Key` header or a"
}
```

```
1 api-authentication-guide.md
1 api-authentication-guide-copy-2.md
1 api-authentication-guide-copy-1.md
```

All 3 result slots are the same content (`content_preview` identical) under
3 different `document_id`s (original + 2 re-uploads under different
filenames). `api-rate-limiting.md` and `api-error-handling.md` —
genuinely distinct, relevant topics — are pushed out of the result set
entirely.

## Conclusion

Filename-only dedup lets identical content multiply storage and search
weight linearly with re-upload count. Combined with no per-document result
diversification in ranking, this floods top-k results with redundant
content and silently drops distinct, relevant documents from view.

## Fix directions (not implemented)

- Content hash (e.g. sha256 of normalized text) as dedup key, independent
  of filename.
- Per-document cap or diversification (MMR-style reranking) in search to
  avoid one doc/duplicate set monopolizing top-k regardless of dedup fix.
