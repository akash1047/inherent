#!/bin/bash
# Run PostgreSQL migrations
#
# Usage:
#   Local:  ./scripts/run_migrations.sh
#   VM:     DATABASE_URL="postgresql://..." ./scripts/run_migrations.sh
#
# Environment Variables:
#   DATABASE_URL - PostgreSQL connection string (required)
#   MIGRATIONS_DIR - Directory containing migration files (default: ./scripts/migrations)
#   DRY_RUN - Set to "true" to only show what would be run

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-${SCRIPT_DIR}/migrations}"
DRY_RUN="${DRY_RUN:-false}"

echo "========================================"
echo "PostgreSQL Migration Runner"
echo "========================================"

# Check for DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    # Try to load from .env file
    if [ -f "${SCRIPT_DIR}/../.env" ]; then
        echo -e "${YELLOW}Loading DATABASE_URL from .env file...${NC}"
        export $(grep -E '^DATABASE_URL=' "${SCRIPT_DIR}/../.env" | xargs)
    fi

    if [ -z "$DATABASE_URL" ]; then
        echo -e "${RED}Error: DATABASE_URL environment variable is required${NC}"
        echo ""
        echo "Usage:"
        echo "  DATABASE_URL=\"postgresql://user:pass@host:5432/db\" ./scripts/run_migrations.sh"
        exit 1
    fi
fi

# Parse DATABASE_URL for display (hide password)
SAFE_URL=$(echo "$DATABASE_URL" | sed -E 's/:([^:@]+)@/:****@/')
echo "Database: ${SAFE_URL}"
echo "Migrations: ${MIGRATIONS_DIR}"
echo "Dry run: ${DRY_RUN}"
echo "========================================"

# Check if migrations directory exists
if [ ! -d "$MIGRATIONS_DIR" ]; then
    echo -e "${RED}Error: Migrations directory not found: ${MIGRATIONS_DIR}${NC}"
    exit 1
fi

# Find all migration files, sorted by name
MIGRATION_FILES=$(find "$MIGRATIONS_DIR" -name "*.sql" -type f | sort)

if [ -z "$MIGRATION_FILES" ]; then
    echo -e "${YELLOW}No migration files found in ${MIGRATIONS_DIR}${NC}"
    exit 0
fi

echo "Found migrations:"
for file in $MIGRATION_FILES; do
    echo "  - $(basename "$file")"
done
echo ""

# Create migrations tracking table if it doesn't exist
INIT_SQL="
CREATE TABLE IF NOT EXISTS _migrations (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"

if [ "$DRY_RUN" = "true" ]; then
    echo -e "${YELLOW}[DRY RUN] Would create _migrations table${NC}"
else
    echo "Initializing migrations table..."
    echo "$INIT_SQL" | psql "$DATABASE_URL" -q 2>/dev/null || {
        # If psql not available, try with docker
        if command -v docker &> /dev/null; then
            echo "$INIT_SQL" | docker run -i --rm --network host postgres:15-alpine psql "$DATABASE_URL" -q
        else
            echo -e "${RED}Error: psql not found. Install PostgreSQL client or use Docker.${NC}"
            exit 1
        fi
    }
fi

# Function to run SQL
run_sql() {
    local sql="$1"
    if command -v psql &> /dev/null; then
        echo "$sql" | psql "$DATABASE_URL" -q
    else
        echo "$sql" | docker run -i --rm --network host postgres:15-alpine psql "$DATABASE_URL" -q
    fi
}

# Function to run SQL file
run_sql_file() {
    local file="$1"
    if command -v psql &> /dev/null; then
        psql "$DATABASE_URL" -f "$file"
    else
        cat "$file" | docker run -i --rm --network host postgres:15-alpine psql "$DATABASE_URL"
    fi
}

# Function to check if migration was already applied
is_applied() {
    local filename="$1"
    local result
    if command -v psql &> /dev/null; then
        result=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM _migrations WHERE filename = '${filename}';" 2>/dev/null | tr -d ' ')
    else
        result=$(echo "SELECT COUNT(*) FROM _migrations WHERE filename = '${filename}';" | docker run -i --rm --network host postgres:15-alpine psql "$DATABASE_URL" -t 2>/dev/null | tr -d ' ')
    fi
    [ "$result" = "1" ]
}

# Run each migration
APPLIED=0
SKIPPED=0
FAILED=0

for file in $MIGRATION_FILES; do
    filename=$(basename "$file")

    if [ "$DRY_RUN" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would apply: ${filename}${NC}"
        ((APPLIED++))
        continue
    fi

    # Check if already applied
    if is_applied "$filename"; then
        echo -e "${YELLOW}⏭  Skipping (already applied): ${filename}${NC}"
        ((SKIPPED++))
        continue
    fi

    echo -e "Applying: ${filename}..."

    # Run the migration
    if run_sql_file "$file"; then
        # Record successful migration
        run_sql "INSERT INTO _migrations (filename) VALUES ('${filename}');"
        echo -e "${GREEN}✅ Applied: ${filename}${NC}"
        ((APPLIED++))
    else
        echo -e "${RED}❌ Failed: ${filename}${NC}"
        ((FAILED++))
        exit 1
    fi
done

echo ""
echo "========================================"
echo "Migration Summary"
echo "========================================"
echo -e "${GREEN}Applied: ${APPLIED}${NC}"
echo -e "${YELLOW}Skipped: ${SKIPPED}${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed: ${FAILED}${NC}"
    exit 1
fi
echo -e "${GREEN}✅ All migrations complete!${NC}"
