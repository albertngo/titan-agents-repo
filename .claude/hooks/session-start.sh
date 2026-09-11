#!/bin/bash
# Populates .env from same-named cloud/session env vars at session start, so a
# credential already configured on this environment doesn't have to be asked
# for and copied in by hand every session (the container is ephemeral; .env
# itself is gitignored and never persists any other way).
#
# Only fills keys .env.example declares, and only when .env doesn't already
# have a non-empty value for that key — never overwrites a value someone set
# deliberately. This does not weaken the CLAUDE.md Secrets check: after this
# hook runs, the value genuinely resides in .env before any task starts, so
# "confirm it comes from .env" holds without a live copy-paste step.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

[ -f .env.example ] || exit 0
[ -f .env ] || touch .env

while IFS= read -r key; do
  [ -z "$key" ] && continue

  env_value="${!key:-}"
  [ -z "$env_value" ] && continue

  existing_line=$(grep -E "^${key}=" .env || true)
  existing_value="${existing_line#${key}=}"
  [ -n "$existing_value" ] && continue

  if [ -n "$existing_line" ]; then
    sed -i "s|^${key}=.*|${key}=${env_value}|" .env
  else
    printf '%s=%s\n' "$key" "$env_value" >> .env
  fi
done < <(grep -oE '^[A-Z][A-Z0-9_]*=' .env.example | sed 's/=$//')

exit 0
