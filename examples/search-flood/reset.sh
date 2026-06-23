#!/bin/bash

# Reset persistent stores and bring up fresh stack
# Usage: ./reset.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Cleaning up existing stack..."
cd "$(git rev-parse --show-toplevel)"
make clean

echo "==> Waiting 2 seconds for cleanup..."
sleep 2

echo "==> Starting fresh stack with bootstrap..."
make dev

echo "==> Creating separate workspaces for test scenarios..."
bash "$SCRIPT_DIR/setup-workspaces.sh"

echo ""
echo "==> Stack ready. API at http://localhost:18000"
echo ""
echo "Test Scenario 1 (3 unique documents):"
echo "  API Key: ink_test_3_unique_key"
echo "  Workspace: ws_search_flood_test_3"
echo ""
echo "Test Scenario 2 (5 documents with duplicates):"
echo "  API Key: ink_test_5_dupes_key"
echo "  Workspace: ws_search_flood_test_5"