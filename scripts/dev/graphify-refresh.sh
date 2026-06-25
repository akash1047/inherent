#!/usr/bin/env bash
#
# graphify-refresh.sh — keep the local knowledge graph (graphify-out/) current.
#
# SECURITY MODEL (read before changing defaults):
#   This script can run from a git post-merge hook, i.e. on content that was
#   JUST PULLED from a remote. Pulled docs are attacker-influenceable. Driving
#   an LLM agent over that content with broad permissions is a prompt-injection
#   -> code-execution risk. So:
#
#     * AST refresh (`graphify update .`) is deterministic parsing — NO agent,
#       no LLM, no injection surface. It runs automatically and always.
#     * The semantic pass uses the Claude Code AGENT (`claude -p`). Unattended
#       agent work needs broad permissions to function, which is exactly the
#       danger on untrusted content. It is therefore OFF by default and only
#       runs when you explicitly opt in AND vouch for the content's trust:
#           GRAPHIFY_ALLOW_AGENT_BYPASS=1
#       Never set that in an unattended hook on a repo that takes outside PRs.
#
# Usage:
#   bash scripts/dev/graphify-refresh.sh [GIT_RANGE]
#     GIT_RANGE  optional "OLD..NEW" range to inspect (default: ORIG_HEAD..HEAD).
#
# Env vars:
#   GRAPHIFY_ALLOW_AGENT_BYPASS=1  opt in to the LLM semantic pass (see above)
#   GRAPHIFY_CC_MODEL              Claude Code model alias/id  (default: haiku)
#   GRAPHIFY_CC_PERM_MODE          permission mode for the opt-in agent pass
#                                  (default: bypassPermissions — required for
#                                   unattended agent work; only reached once
#                                   GRAPHIFY_ALLOW_AGENT_BYPASS=1 is set)
#   GRAPHIFY_REFRESH_SYNC=1        run in foreground instead of detaching
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

LOG="graphify-out/.refresh.log"
mkdir -p graphify-out

ALLOW_AGENT="${GRAPHIFY_ALLOW_AGENT_BYPASS:-0}"
CC_MODEL="${GRAPHIFY_CC_MODEL:-haiku}"
CC_PERM_MODE="${GRAPHIFY_CC_PERM_MODE:-bypassPermissions}"

log() { printf '[graphify-refresh %s] %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG"; }

if ! command -v graphify >/dev/null 2>&1; then
  log "graphify not on PATH — skipping refresh. Install with: pip install graphifyy"
  exit 0
fi

# Determine the commit range that just landed.
RANGE="${1:-}"
if [ -z "$RANGE" ]; then
  if git rev-parse --verify -q ORIG_HEAD >/dev/null; then
    RANGE="ORIG_HEAD..HEAD"
  else
    RANGE="HEAD~1..HEAD"
  fi
fi

CHANGED="$(git diff --name-only "$RANGE" 2>/dev/null || true)"
if [ -z "$CHANGED" ]; then
  log "no changed files detected for range '$RANGE' — nothing to do."
  exit 0
fi

CODE_RE='\.(py|ts|tsx|js|jsx|go|rs|java|cpp|cc|cxx|hpp|h|rb|swift|kt|kts|cs|scala|php|lua|sql)$'
NONCODE="$(printf '%s\n' "$CHANGED" | grep -Ev "$CODE_RE" || true)"

ast_refresh() {
  graphify update . >>"$LOG" 2>&1 \
    && log "AST refresh complete." \
    || log "AST refresh FAILED — see $LOG"
}

run_refresh() {
  # Always do the safe, free, deterministic code refresh.
  log "AST refresh ($(printf '%s\n' "$CHANGED" | wc -l | tr -d ' ') changed files)"
  ast_refresh

  # Nothing semantic to do if only code changed.
  if [ -z "$NONCODE" ]; then
    return
  fi

  # Doc/concept files changed -> semantic re-extraction wanted.
  if [ "$ALLOW_AGENT" != "1" ]; then
    log "doc/concept changes detected but the LLM semantic pass is DISABLED by default"
    log "  (security: would run an agent over just-pulled, possibly untrusted content)."
    log "  Code structure is current. To refresh semantic nodes on content you TRUST, run:"
    log "    GRAPHIFY_ALLOW_AGENT_BYPASS=1 make graphify-refresh"
    return
  fi

  if ! command -v claude >/dev/null 2>&1; then
    log "agent pass opted in but 'claude' CLI not found — semantic skipped (AST is current)."
    return
  fi

  log "AGENT SEMANTIC PASS (opt-in): /graphify --update via Claude Code (model: $CC_MODEL, perm: $CC_PERM_MODE)"
  log "  Trust assumption: you have vouched for the merged content. Do NOT enable this unattended on outside PRs."
  claude -p "/graphify --update ." \
    --model "$CC_MODEL" \
    --permission-mode "$CC_PERM_MODE" \
    >>"$LOG" 2>&1 \
    && log "Semantic refresh complete." \
    || log "Semantic refresh FAILED — see $LOG"
}

if [ "${GRAPHIFY_REFRESH_SYNC:-0}" = "1" ]; then
  run_refresh
else
  ( run_refresh ) >/dev/null 2>&1 &
  log "refresh started in background (pid $!). Tail with: tail -f $LOG"
fi
