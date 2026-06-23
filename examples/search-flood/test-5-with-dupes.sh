#!/bin/bash

# Test scenario: Upload 5 docs (3 unique + 2 copies), search, show flooded results
# Expected: Results polluted with duplicates from same source document

set -e

API_BASE="http://localhost:18000"
API_KEY="ink_test_5_dupes_key"
WORKSPACE_ID="ws_search_flood_test_5"
SEARCH_QUERY="API authentication token"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "TEST: 5 Documents with Duplicates"
echo "(3 unique + 2 copies of auth guide)"
echo "=========================================="
echo ""

# Step 1: Upload 5 files
echo "Step 1: Uploading 5 documents..."
echo ""

DOC_IDS=()

for file in \
    api-authentication-guide.md \
    api-authentication-guide-copy-1.md \
    api-authentication-guide-copy-2.md \
    api-rate-limiting.md \
    api-error-handling.md; do

    echo "  Uploading: $file"
    RESPONSE=$(curl -s -X POST "$API_BASE/v1/documents" \
        -H "X-API-Key: $API_KEY" \
        -H "X-Workspace-Id: $WORKSPACE_ID" \
        -F "file=@$SCRIPT_DIR/$file;type=text/markdown")

    DOC_ID=$(echo "$RESPONSE" | jq -r '.document_id')
    DOC_IDS+=("$DOC_ID")
    STATUS=$(echo "$RESPONSE" | jq -r '.status')

    echo "    ✓ Document ID: $DOC_ID (status: $STATUS)"
done

echo ""
echo "Step 2: Waiting for ingestion to complete..."

# Poll until all documents processed
for i in {1..30}; do
    PROCESSED=0
    for DOC_ID in "${DOC_IDS[@]}"; do
        STATUS=$(curl -s "$API_BASE/v1/documents/$DOC_ID" \
            -H "X-API-Key: $API_KEY" \
            -H "X-Workspace-Id: $WORKSPACE_ID" | jq -r '.status')

        if [ "$STATUS" = "processed" ]; then
            PROCESSED=$((PROCESSED + 1))
        fi
    done

    echo "  [$i/30] Processed: $PROCESSED/5 documents"

    if [ $PROCESSED -eq 5 ]; then
        echo "✓ All documents processed"
        break
    fi

    sleep 2
done

echo ""
echo "Step 3: Searching with query: '$SEARCH_QUERY'"
echo ""

SEARCH_RESPONSE=$(curl -s -X POST "$API_BASE/v1/search" \
    -H "X-API-Key: $API_KEY" \
    -H "X-Workspace-Id: $WORKSPACE_ID" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"$SEARCH_QUERY\",\"limit\":3}")

echo "Search Results:"
echo ""

RESULT_COUNT=$(echo "$SEARCH_RESPONSE" | jq '.results | length')
echo "Total results: $RESULT_COUNT"
echo ""

if [ "$RESULT_COUNT" -gt 0 ]; then
    echo "$SEARCH_RESPONSE" | jq '.results[] | {
        document_id: .document_id,
        document_name: .document_name,
        chunk_id: .chunk_id,
        content_preview: .content[0:100]
    }' | sed 's/^/  /'
else
    echo "  (no results)"
fi

echo ""
echo "Step 4: Analyze duplication..."
echo ""

# Count results by document name
DOC_COUNTS=$(echo "$SEARCH_RESPONSE" | jq -r '.results[].document_name' | sort | uniq -c | sort -rn)
echo "Results per document:"
echo "$DOC_COUNTS" | sed 's/^/  /'

echo ""
echo "=========================================="
echo "Expected: top-3 slots flooded by auth-guide"
echo "         duplicates; rate-limiting and"
echo "         error-handling docs pushed out"
echo "Actual: $RESULT_COUNT total results"
echo "=========================================="