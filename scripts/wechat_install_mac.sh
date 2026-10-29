#!/bin/zsh
# One-time setup of the WeChat archiver on Albert's Mac. See methods/wechat-archive.md.
#
#   zsh scripts/wechat_install_mac.sh            # venv + launchd job
#   zsh scripts/wechat_install_mac.sh --uninstall
#
# Installs wechat-mcp-server pinned to the commit that was read before this was
# built, into its own venv at .venv-wechat/, and a LaunchAgent that starts
# scripts/wechat_archive.py every 30 minutes. The archiver itself decides whether
# a run is due (platform-settings/wechat.json, archive.schedule): normally the first
# moment after 06:00 that the Mac is unlocked and idle, once a day. Touches nothing else.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="ca.titanfloors.wechat-archive"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/titan-wechat-archive"
VENV="$REPO/.venv-wechat"
# Reviewed 2026-10-29 (read functions only are used; see tests/test_wechat.py).
WECHAT_MCP="git+https://github.com/BiboyQG/WeChat-MCP@cc470367ca6613b129f7e2bb742e6cc57df8c4d6"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL. The venv at $VENV and the Notion archive are untouched."
  exit 0
fi

EVERY="$("${PYTHON_FOR_SETTINGS:-python3}" -c 'import json,sys; print(json.load(open(sys.argv[1]))["archive"]["schedule"]["every_minutes"])' "$REPO/platform-settings/wechat.json" 2>/dev/null || echo 30)"

PY=""
for cand in python3.13 python3.12 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    PY="$(command -v "$cand")"; break
  fi
done
if [[ -z "$PY" ]]; then
  echo "Need Python 3.12 or newer (brew install python@3.12)." >&2
  exit 1
fi

[[ -d "$VENV" ]] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$WECHAT_MCP"

if ! grep -q '^NOTION_WECHAT_WRITE_TOKEN=.\+' "$REPO/.env" 2>/dev/null; then
  echo "Add NOTION_WECHAT_WRITE_TOKEN=<writer integration secret> to $REPO/.env, then re-run." >&2
  exit 1
fi

mkdir -p "$LOGDIR" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>$REPO/scripts/wechat_archive.py</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>$((EVERY * 60))</integer>
  <key>StandardOutPath</key><string>$LOGDIR/runs.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/errors.log</string>
  <key>EnvironmentVariables</key><dict><key>TZ</key><string>America/Toronto</string></dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

REAL_PY="$("$VENV/bin/python" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
cat <<EOF

Installed: tries every $EVERY minutes; runs once a day when the Mac is unlocked and idle.
Logs: $LOGDIR

Before the first scheduled run, grant this Python both permissions in
System Settings > Privacy & Security:
  Accessibility     -> $REAL_PY
  Screen Recording  -> $REAL_PY
(Press + and Cmd-Shift-G to paste the path.) Then do the supervised first run:

  $VENV/bin/python scripts/wechat_archive.py --dry-run --no-idle-check --chat "<one chat name>"
EOF
