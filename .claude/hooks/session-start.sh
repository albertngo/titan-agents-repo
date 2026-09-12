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

# ── Python dependencies, from the repo's own vendored wheels ─────────────────
# Added 2026-09-12. The container is ephemeral and pypi.org is off this
# environment's egress allowlist, so dependencies come from vendor/wheels/ —
# committed to git, installed as a local file copy with no network.
#
# This makes the tooling AVAILABLE. It does not enforce anything: if the install
# fails, /process-price-list step 2.0 refuses to extract rather than substituting
# another method. Those are deliberately two separate mechanisms.
#
# Never hard-fail the session on this. A non-zero exit here blocks session start
# entirely, including for the many tasks that need no PDF tooling at all.

if python3 -c "import pdfplumber" 2>/dev/null; then
  :  # already present, nothing to do
elif [ -f requirements.lock.txt ] && compgen -G "vendor/wheels/*.whl" >/dev/null 2>&1; then
  if pip install --no-index --find-links vendor/wheels --only-binary=:all: \
       --require-hashes -r requirements.lock.txt >/tmp/pip-vendor.log 2>&1; then
    echo "deps: installed from vendor/wheels ($(python3 -c 'import pdfplumber; print(pdfplumber.__version__)' 2>/dev/null))"
  else
    echo "deps: vendored install FAILED — see /tmp/pip-vendor.log"
    echo "      price-list extraction will flag and stop (step 2.0). Other work is unaffected."
  fi
else
  echo "deps: vendor/wheels is not populated, so pdfplumber is unavailable."
  echo "      Price-list extraction will flag and stop (step 2.0), by design."
  echo "      To fix: follow the one-time fetch in vendor/wheels/README.md"
  echo "      (needs pypi.org + files.pythonhosted.org temporarily allowlisted)."
fi

exit 0
