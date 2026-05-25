#!/bin/bash
set -euo pipefail

RUNTIME_ROOT="${MCP_BROKER_RUNTIME_ROOT:-$HOME/mcp/mcp-broker}"
SERVICE_NAME="${MCP_BROKER_SYSTEMD_SERVICE:-mcp-broker.service}"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SYSTEMD_USER_DIR/$SERVICE_NAME"
PLAN_PATH="$RUNTIME_ROOT/renders/uninstall-$SERVICE_NAME.txt"
MODE="dry-run"

usage() {
  cat <<'USAGE'
usage: uninstall-systemd-user.sh [--dry-run|--apply] [--help]

Plans or removes the mcp-broker systemd user service. Dry-run is the default.
USAGE
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

if [[ "$MODE" == "dry-run" ]]; then
  mkdir -p "$(dirname "$PLAN_PATH")"
  printf "target_path=%s\n" "$SERVICE_PATH" > "$PLAN_PATH"
  printf "dry_run=true plan_path=%s target_path=%s\n" "$PLAN_PATH" "$SERVICE_PATH"
  exit 0
fi

rm -f "$SERVICE_PATH"
printf "dry_run=false target_path=%s\n" "$SERVICE_PATH"
