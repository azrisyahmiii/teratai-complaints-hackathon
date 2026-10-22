#!/usr/bin/env bash
# Stop hook: typecheck + lint web/ and backend/. Exit 2 blocks the stop and shows stderr to Claude.
input=$(cat)
# Already re-prompted once by this hook: let Claude stop rather than loop.
echo "$input" | grep -q '"stop_hook_active": *true' && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0
fail=""
log="${TMPDIR:-${TEMP:-/tmp}}/claude-stop-check.txt"
: > "$log"

if [ -n "$(git status --porcelain -- web)" ]; then
  (cd web && npm run -s typecheck && npm run -s lint) >> "$log" 2>&1 || fail="$fail web"
fi
if [ -n "$(git status --porcelain -- backend)" ]; then
  (cd backend && uv run -q mypy src && uv run -q ruff check) >> "$log" 2>&1 || fail="$fail backend"
fi

if [ -n "$fail" ]; then
  { echo "Stop hook: typecheck/lint failed in:$fail. Fix before finishing."; tail -40 "$log"; } >&2
  exit 2
fi
exit 0
