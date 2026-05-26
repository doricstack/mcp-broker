#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${MCP_BROKER_RELEASE_SMOKE_DIR:-}"
KEEP_WORK_DIR="${MCP_BROKER_RELEASE_SMOKE_KEEP:-0}"

usage() {
  cat <<'USAGE'
usage: release-smoke.sh [--help]

Creates a clean tree and runs the setup path:
  make config-init
  make setup
  make config-validate
  make broker-smoke

Environment:
  MCP_BROKER_RELEASE_SMOKE_DIR    Optional existing work directory
  MCP_BROKER_RELEASE_SMOKE_KEEP   Set to 1 to keep the temporary directory
  PYTHON_BIN                      Python used to run the private export helper
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

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-release-smoke.XXXXXX")"
fi

cleanup() {
  if [[ "$KEEP_WORK_DIR" != "1" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

CLONE_DIR="$WORK_DIR/source"
RUNTIME_ROOT="$WORK_DIR/runtime"
HOME_DIR="$WORK_DIR/home"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$CLONE_DIR" "$RUNTIME_ROOT" "$HOME_DIR"
XDG_CONFIG_HOME_DIR="$HOME_DIR/.config"
mkdir -p "$XDG_CONFIG_HOME_DIR"

if [[ -f "$ROOT/scripts/public-export.py" && -f "$ROOT/public-export/allowlist.txt" ]]; then
  "$PYTHON_BIN" "$ROOT/scripts/public-export.py" \
    --repo-root "$ROOT" \
    --public-repo "$CLONE_DIR" \
    --allowlist "$ROOT/public-export/allowlist.txt" \
    --denylist "$ROOT/public-export/denylist.txt"
else
  tar \
    --exclude .git \
    --exclude .pytest_cache \
    --exclude .mutmut-cache \
    --exclude build \
    --exclude dist \
    --exclude htmlcov \
    --exclude mutants \
    --exclude var \
    --exclude venv-mcp-broker \
    -C "$ROOT" -cf - . | tar -C "$CLONE_DIR" -xf -
fi

(cd "$CLONE_DIR" && HOME="$HOME_DIR" XDG_CONFIG_HOME="$XDG_CONFIG_HOME_DIR" make config-init RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$CLONE_DIR" && HOME="$HOME_DIR" XDG_CONFIG_HOME="$XDG_CONFIG_HOME_DIR" make setup RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$CLONE_DIR" && HOME="$HOME_DIR" XDG_CONFIG_HOME="$XDG_CONFIG_HOME_DIR" make config-validate RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$CLONE_DIR" && HOME="$HOME_DIR" XDG_CONFIG_HOME="$XDG_CONFIG_HOME_DIR" make broker-smoke RUNTIME_ROOT="$RUNTIME_ROOT")

PRIVATE_PATH_MARKER="/""Users/"
if grep -R "$PRIVATE_PATH_MARKER" "$CLONE_DIR/README.md" "$CLONE_DIR/docs" "$CLONE_DIR/config" "$CLONE_DIR/scripts" >/dev/null 2>&1; then
  printf "release smoke found a private path marker\n" >&2
  exit 1
fi

printf "release_smoke=true work_dir=%s runtime_root=%s\n" "$WORK_DIR" "$RUNTIME_ROOT"
