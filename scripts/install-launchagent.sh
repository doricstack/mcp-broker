#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${MCP_BROKER_RUNTIME_ROOT:-$HOME/mcp/mcp-broker}"
SOCKET_PATH="${MCP_BROKER_SOCKET:-$RUNTIME_ROOT/sockets/broker.sock}"
CONFIG_PATH="${MCP_BROKER_CONFIG:-$ROOT/config/broker.example.yaml}"
BROKER_RUNTIME_PATH="${MCP_BROKER_RUNTIME_PATH:-${PATH:-/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin}}"
LAUNCHAGENT_LABEL="com.mcp-broker.agent"
PLIST_NAME="$LAUNCHAGENT_LABEL.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
RENDER_PATH="$RUNTIME_ROOT/renders/$PLIST_NAME"
BACKUP_PATH=""
MODE="dry-run"

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  printf "%s" "$value"
}

write_plist() {
  local target_path="$1"
  mkdir -p "$(dirname "$target_path")"
  cat > "$target_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LAUNCHAGENT_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/venv-mcp-broker/bin/python</string>
    <string>-m</string>
    <string>mcp_broker.daemon</string>
    <string>serve</string>
    <string>--runtime-root</string>
    <string>$RUNTIME_ROOT</string>
    <string>--socket-path</string>
    <string>$SOCKET_PATH</string>
    <string>--config</string>
    <string>$CONFIG_PATH</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>$ROOT/src</string>
    <key>PATH</key>
    <string>$(xml_escape "$BROKER_RUNTIME_PATH")</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$RUNTIME_ROOT/logs/launchagent.out.log</string>
  <key>StandardErrorPath</key>
  <string>$RUNTIME_ROOT/logs/launchagent.err.log</string>
</dict>
</plist>
PLIST
}

backup_existing_plist() {
  if [[ ! -f "$PLIST_PATH" ]]; then
    return 0
  fi
  local backup_dir="$RUNTIME_ROOT/backups/launchagent"
  local label
  label="$(date -u +"%Y%m%dT%H%M%SZ")"
  BACKUP_PATH="$backup_dir/$label.$PLIST_NAME"
  mkdir -p "$backup_dir"
  cp "$PLIST_PATH" "$BACKUP_PATH"
}

for arg in "$@"; do
  case "$arg" in
    --apply)
      MODE="apply"
      ;;
    --dry-run)
      MODE="dry-run"
      ;;
    *)
      printf "unknown argument: %s\n" "$arg" >&2
      exit 2
      ;;
  esac
done

set +e
make -C "$ROOT" broker-smoke RUNTIME_ROOT="$RUNTIME_ROOT" SOCKET_PATH="$SOCKET_PATH" CONFIG_PATH="$CONFIG_PATH"
SMOKE_STATUS=$?
set -e

if [[ "$SMOKE_STATUS" -ne 0 ]]; then
  printf "broker-smoke failed; refusing LaunchAgent install\n" >&2
  exit "$SMOKE_STATUS"
fi

if [[ "$MODE" == "dry-run" ]]; then
  write_plist "$RENDER_PATH"
  printf "dry_run=true rendered_path=%s target_path=%s\n" "$RENDER_PATH" "$PLIST_PATH"
  exit 0
fi

backup_existing_plist
write_plist "$PLIST_PATH"
printf "dry_run=false target_path=%s backup_path=%s\n" "$PLIST_PATH" "$BACKUP_PATH"
