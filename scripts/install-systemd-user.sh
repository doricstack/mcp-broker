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
# File-descriptor ceiling for the daemon (see install-launchagent.sh for rationale).
# systemd user services inherit a low default; the broker needs headroom for many
# upstream subprocess pipes across concurrent LLM clients.
BROKER_MAX_OPEN_FILES="${MCP_BROKER_MAX_OPEN_FILES:-8192}"
SERVICE_NAME="${MCP_BROKER_SYSTEMD_SERVICE:-mcp-broker.service}"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SYSTEMD_USER_DIR/$SERVICE_NAME"
RENDER_PATH="$RUNTIME_ROOT/renders/$SERVICE_NAME"
BACKUP_PATH=""
MODE="dry-run"

usage() {
  cat <<'USAGE'
usage: install-systemd-user.sh [--dry-run|--apply] [--help]

Renders a systemd user service for mcp-broker. Dry-run is the default.

Environment:
  MCP_BROKER_RUNTIME_ROOT      Runtime root, default: $HOME/mcp/mcp-broker
  MCP_BROKER_SOCKET            Broker socket path
  MCP_BROKER_CONFIG            Broker config path
  MCP_BROKER_DAEMON_COMMAND    Optional daemon command override
  MCP_BROKER_SYSTEMD_SERVICE   Service filename, default: mcp-broker.service
USAGE
}

daemon_command() {
  if [[ -n "${MCP_BROKER_DAEMON_COMMAND:-}" ]]; then
    printf "%s" "$MCP_BROKER_DAEMON_COMMAND"
    return 0
  fi
  if [[ -x "$ROOT/venv-mcp-broker/bin/python" ]]; then
    printf "%s -m mcp_broker.daemon" "$ROOT/venv-mcp-broker/bin/python"
    return 0
  fi
  if command -v mcp-broker-daemon >/dev/null 2>&1; then
    command -v mcp-broker-daemon
    return 0
  fi
  printf "mcp-broker-daemon"
}

write_service() {
  local target_path="$1"
  local command_line
  command_line="$(daemon_command)"
  mkdir -p "$(dirname "$target_path")"
  cat > "$target_path" <<SERVICE
[Unit]
Description=mcp-broker local MCP daemon

[Service]
Type=simple
WorkingDirectory=$ROOT
Environment=PYTHONPATH=$ROOT/src
Environment=PATH=$BROKER_RUNTIME_PATH
Environment=MCP_BROKER_RUNTIME_ROOT=$RUNTIME_ROOT
Environment=MCP_BROKER_SOCKET=$SOCKET_PATH
Environment=MCP_BROKER_CONFIG=$CONFIG_PATH
ExecStart=$command_line serve --runtime-root $RUNTIME_ROOT --socket-path $SOCKET_PATH --config $CONFIG_PATH
Restart=on-failure
RestartSec=3
LimitNOFILE=$BROKER_MAX_OPEN_FILES
StandardOutput=append:$RUNTIME_ROOT/logs/systemd.out.log
StandardError=append:$RUNTIME_ROOT/logs/systemd.err.log

[Install]
WantedBy=default.target
SERVICE
}

backup_existing_service() {
  if [[ ! -f "$SERVICE_PATH" ]]; then
    return 0
  fi
  local backup_dir="$RUNTIME_ROOT/backups/systemd"
  local label
  label="$(date -u +"%Y%m%dT%H%M%SZ")"
  BACKUP_PATH="$backup_dir/$label.$SERVICE_NAME"
  mkdir -p "$backup_dir"
  cp "$SERVICE_PATH" "$BACKUP_PATH"
}

for arg in "$@"; do
  case "$arg" in
    --apply)
      MODE="apply"
      ;;
    --dry-run)
      MODE="dry-run"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf "unknown argument: %s\n" "$arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

set +e
make -C "$ROOT" broker-smoke RUNTIME_ROOT="$RUNTIME_ROOT" SOCKET_PATH="$SOCKET_PATH" CONFIG_PATH="$CONFIG_PATH"
SMOKE_STATUS=$?
set -e

if [[ "$SMOKE_STATUS" -ne 0 ]]; then
  printf "broker-smoke failed; refusing systemd user-service install\n" >&2
  exit "$SMOKE_STATUS"
fi

if [[ "$MODE" == "dry-run" ]]; then
  write_service "$RENDER_PATH"
  printf "dry_run=true rendered_path=%s target_path=%s\n" "$RENDER_PATH" "$SERVICE_PATH"
  exit 0
fi

backup_existing_service
write_service "$SERVICE_PATH"
printf "dry_run=false target_path=%s backup_path=%s\n" "$SERVICE_PATH" "$BACKUP_PATH"
