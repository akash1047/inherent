#!/bin/bash

# Test scenario: Upload 3 unique docs, search, show clean results
# Expected: 3 results from 3 different documents (no duplicates)

set -e

API_BASE="http://localhost:18000"
API_KEY="ink_test_3_unique_key"
WORKSPACE_ID="ws_search_flood_test_3"
SEARCH_QUERY="API authentication token"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "TEST: 3 Unique Documents (Clean Scenario)"
echo "=========================================="
echo ""

# Step 1: Upload 3 unique files
echo "Step 1: Uploading 3 unique documents..."
echo ""

DOC_IDS=()

for file in api-authentication-guide.md api-rate-limiting.md api-error-handling.md; do
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

    echo "  [$i/30] Processed: $PROCESSED/3 documents"

    if [ $PROCESSED -eq 3 ]; then
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
echo "=========================================="
echo "Expected: 3 results from 3 different docs"
echo "Actual: $RESULT_COUNT results"
echo "=========================================="