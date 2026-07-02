#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${MCP_BROKER_WINDOWS_SMOKE_DIR:-}"

usage() {
  cat <<'USAGE'
usage: windows-powershell-smoke.sh [--help]

Runs PowerShell parser/help checks and Windows Scheduled Task dry-runs without
registering a task. Requires PowerShell Core (`pwsh`) or Windows PowerShell.
USAGE
}

for arg in "$@"; do
  case "$arg" in
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

if command -v pwsh >/dev/null 2>&1; then
  PWSH=pwsh
elif command -v powershell.exe >/dev/null 2>&1; then
  PWSH=powershell.exe
else
  printf "PowerShell is required for windows-powershell-smoke\n" >&2
  exit 2
fi

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-windows-smoke.XXXXXX")"
fi

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$WORK_DIR/home" "$WORK_DIR/runtime"
export PIP_DISABLE_PIP_VERSION_CHECK=1

"$PWSH" -NoProfile -ExecutionPolicy Bypass -File "$ROOT/scripts/install-windows-task.ps1" -Help >/dev/null
"$PWSH" -NoProfile -ExecutionPolicy Bypass -File "$ROOT/scripts/uninstall-windows-task.ps1" -Help >/dev/null

USERPROFILE="$WORK_DIR/home" \
MCP_BROKER_RUNTIME_ROOT="$WORK_DIR/runtime" \
MCP_BROKER_SOCKET="$WORK_DIR/runtime/sockets/broker.sock" \
MCP_BROKER_CONFIG="$ROOT/config/broker.example.yaml" \
"$PWSH" -NoProfile -ExecutionPolicy Bypass -File "$ROOT/scripts/install-windows-task.ps1" -DryRun >/dev/null

USERPROFILE="$WORK_DIR/home" \
MCP_BROKER_RUNTIME_ROOT="$WORK_DIR/runtime" \
"$PWSH" -NoProfile -ExecutionPolicy Bypass -File "$ROOT/scripts/uninstall-windows-task.ps1" -DryRun >/dev/null

test -f "$WORK_DIR/runtime/renders/windows-task-mcp-broker.txt"
test -f "$WORK_DIR/runtime/renders/uninstall-windows-task-mcp-broker.txt"

printf "windows_powershell_smoke=true\n"
