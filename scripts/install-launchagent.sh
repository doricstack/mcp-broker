#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${MCP_BROKER_RUNTIME_ROOT:-$HOME/mcp/mcp-broker}"
SOCKET_PATH="${MCP_BROKER_SOCKET:-$RUNTIME_ROOT/sockets/broker.sock}"
# Prefer the private runtime config when it exists (the normal installed state);
# fall back to the shipped public template for a fresh clone that has not run
# `make config-init` yet.
DEFAULT_CONFIG_PATH="$ROOT/config/broker.private.yaml"
[ -f "$DEFAULT_CONFIG_PATH" ] || DEFAULT_CONFIG_PATH="$ROOT/config/broker.example.yaml"
CONFIG_PATH="${MCP_BROKER_CONFIG:-$DEFAULT_CONFIG_PATH}"
BROKER_RUNTIME_PATH="${MCP_BROKER_RUNTIME_PATH:-${PATH:-/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin}}"
# File-descriptor ceiling for the daemon. The broker multiplexes many upstream
# subprocesses (3+ pipes each) across concurrent LLM clients; launchd's default
# soft limit (256) is far too low and causes "Too many open files" / dropped
# client transports under load. See docs and the idle-upstream janitor.
BROKER_MAX_OPEN_FILES="${MCP_BROKER_MAX_OPEN_FILES:-8192}"
BROKER_MAX_OPEN_FILES_HARD="${MCP_BROKER_MAX_OPEN_FILES_HARD:-16384}"
LAUNCHAGENT_LABEL="com.mcp-broker.agent"
BUNDLE_IDENTIFIER="${MCP_BROKER_LAUNCHAGENT_BUNDLE_ID:-$LAUNCHAGENT_LABEL}"
APP_NAME="${MCP_BROKER_LAUNCHAGENT_APP_NAME:-mcp-broker}"
APP_BUNDLE_PATH="${MCP_BROKER_LAUNCHAGENT_APP_PATH:-$RUNTIME_ROOT/launchagent/$APP_NAME.app}"
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
  <key>AssociatedBundleIdentifiers</key>
  <array>
    <string>$BUNDLE_IDENTIFIER</string>
  </array>
  <key>LimitLoadToSessionType</key>
  <string>Aqua</string>
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
  <key>SoftResourceLimits</key>
  <dict>
    <key>NumberOfFiles</key>
    <integer>$BROKER_MAX_OPEN_FILES</integer>
  </dict>
  <key>HardResourceLimits</key>
  <dict>
    <key>NumberOfFiles</key>
    <integer>$BROKER_MAX_OPEN_FILES_HARD</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$RUNTIME_ROOT/logs/launchagent.out.log</string>
  <key>StandardErrorPath</key>
  <string>$RUNTIME_ROOT/logs/launchagent.err.log</string>
</dict>
</plist>
PLIST
}

write_app_bundle() {
  local contents_dir="$APP_BUNDLE_PATH/Contents"
  local macos_dir="$contents_dir/MacOS"
  local resources_dir="$contents_dir/Resources"
  mkdir -p "$macos_dir" "$resources_dir"

  cat > "$contents_dir/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_IDENTIFIER</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSBackgroundOnly</key>
  <true/>
</dict>
</plist>
PLIST

  cat > "$macos_dir/$APP_NAME" <<SH
#!/bin/bash
exec "$ROOT/venv-mcp-broker/bin/python" -m mcp_broker.daemon status --runtime-root "$RUNTIME_ROOT" --socket-path "$SOCKET_PATH"
SH
  chmod 755 "$macos_dir/$APP_NAME"
}

register_app_bundle() {
  local lsregister="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  if [[ -x "$lsregister" ]]; then
    "$lsregister" -f "$APP_BUNDLE_PATH" >/dev/null 2>&1 || true
  fi
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
write_app_bundle
register_app_bundle
write_plist "$PLIST_PATH"
printf "dry_run=false target_path=%s backup_path=%s app_bundle=%s\n" "$PLIST_PATH" "$BACKUP_PATH" "$APP_BUNDLE_PATH"
