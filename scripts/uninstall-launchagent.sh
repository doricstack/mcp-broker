#!/bin/bash
set -euo pipefail

RUNTIME_ROOT="${MCP_BROKER_RUNTIME_ROOT:-$HOME/mcp/mcp-broker}"
LAUNCHAGENT_LABEL="com.mcp-broker.agent"
PLIST_NAME="$LAUNCHAGENT_LABEL.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
PLAN_PATH="$RUNTIME_ROOT/renders/uninstall-$PLIST_NAME.txt"
MODE="dry-run"

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

if [[ "$MODE" == "dry-run" ]]; then
  mkdir -p "$(dirname "$PLAN_PATH")"
  printf "target_path=%s\n" "$PLIST_PATH" > "$PLAN_PATH"
  printf "dry_run=true plan_path=%s target_path=%s\n" "$PLAN_PATH" "$PLIST_PATH"
  exit 0
fi

rm -f "$PLIST_PATH"
printf "dry_run=false target_path=%s\n" "$PLIST_PATH"
