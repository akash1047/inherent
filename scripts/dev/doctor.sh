#!/usr/bin/env bash
set -uo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

errors=0

ok()   { printf "${GREEN}[OK]${RESET}  %s\n" "$1"; }
fail() { printf "${RED}[FAIL]${RESET} %s\n        → docker compose logs %s\n" "$1" "$2"; errors=$((errors + 1)); }

check_curl() {
  local label=$1 url=$2 svc=$3
  if curl -fsS --max-time 5 "$url" > /dev/null 2>&1; then
    ok "$label"
  else
    fail "$label — $url" "$svc"
  fi
}

check_exec() {
  local label=$1 svc=$2
  shift 2
  if docker compose exec -T "$svc" "$@" > /dev/null 2>&1; then
    ok "$label"
  else
    fail "$label" "$svc"
  fi
}

printf "\n${BOLD}Inherent local stack — health check${RESET}\n\n"

check_exec "postgres          :15432" postgres  pg_isready -U postgres
check_exec "mongodb           :27018" mongodb   mongosh --quiet --eval "db.adminCommand('ping')"
check_curl "weaviate          :18080" http://localhost:18080/v1/.well-known/ready weaviate
check_exec "valkey            :16379" valkey    valkey-cli ping
check_curl "s3rver            :19000" http://localhost:19000 s3rver
check_curl "text-embeddings   :18088" http://localhost:18088/health text-embeddings-inference
check_curl "temporal-ui       :18233" http://localhost:18233/api/v1/namespaces temporal-ui
check_curl "inh-ingestion-svc :18002" http://localhost:18002/health inh-ingestion-svc
check_curl "inh-public-api-svc:18000" http://localhost:18000/health inh-public-api-svc

printf "\n"
if [ "$errors" -eq 0 ]; then
  printf "${GREEN}All services healthy.${RESET}\n\n"
  exit 0
else
  printf "${RED}%d service(s) not ready.${RESET} Run ${BOLD}make logs SVC=<service>${RESET} for details.\n\n" "$errors"
  exit 1
fi
