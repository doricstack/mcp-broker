#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${MCP_BROKER_PUBLIC_RELEASE_DIR:-}"
KEEP_WORK_DIR="${MCP_BROKER_PUBLIC_RELEASE_KEEP:-0}"
MAKE_BIN="${MAKE_BIN:-make}"

usage() {
  cat <<'USAGE'
usage: public-release-dry-run.sh [--help]

Exports the public file set into a clean checkout and runs:
  make setup
  make config-validate
  make broker-smoke
  make test-unit
  make test-journey

Environment:
  MCP_BROKER_PUBLIC_RELEASE_DIR    Optional existing work directory
  MCP_BROKER_PUBLIC_RELEASE_KEEP   Set to 1 to keep the temporary directory
  MAKE_BIN                         make command to use
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
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-public-release.XXXXXX")"
fi

cleanup() {
  if [[ "$KEEP_WORK_DIR" != "1" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

PUBLIC_REPO="$WORK_DIR/public"
RUNTIME_ROOT="$WORK_DIR/runtime"
HOME_DIR="$WORK_DIR/home"

mkdir -p "$PUBLIC_REPO" "$RUNTIME_ROOT" "$HOME_DIR"

(cd "$ROOT" && "$MAKE_BIN" public-export-check PUBLIC_REPO="$PUBLIC_REPO")
(cd "$PUBLIC_REPO" && HOME="$HOME_DIR" "$MAKE_BIN" setup RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$PUBLIC_REPO" && HOME="$HOME_DIR" "$MAKE_BIN" config-validate RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$PUBLIC_REPO" && HOME="$HOME_DIR" "$MAKE_BIN" broker-smoke RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$PUBLIC_REPO" && HOME="$HOME_DIR" "$MAKE_BIN" test-unit RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$PUBLIC_REPO" && HOME="$HOME_DIR" "$MAKE_BIN" test-journey RUNTIME_ROOT="$RUNTIME_ROOT")

printf "public_release_dry_run=true work_dir=%s public_repo=%s runtime_root=%s\n" "$WORK_DIR" "$PUBLIC_REPO" "$RUNTIME_ROOT"
