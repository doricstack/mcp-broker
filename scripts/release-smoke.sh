#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${MCP_BROKER_RELEASE_SMOKE_DIR:-}"
KEEP_WORK_DIR="${MCP_BROKER_RELEASE_SMOKE_KEEP:-0}"

usage() {
  cat <<'USAGE'
usage: release-smoke.sh [--help]

Creates a clean tree from tracked files and runs the public setup path:
  make config-init
  make setup
  make config-validate
  make broker-smoke

Environment:
  MCP_BROKER_RELEASE_SMOKE_DIR    Optional existing work directory
  MCP_BROKER_RELEASE_SMOKE_KEEP   Set to 1 to keep the temporary directory
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

ARCHIVE_PATH="$WORK_DIR/source.tar"
CLONE_DIR="$WORK_DIR/source"
RUNTIME_ROOT="$WORK_DIR/runtime"
HOME_DIR="$WORK_DIR/home"

mkdir -p "$CLONE_DIR" "$RUNTIME_ROOT" "$HOME_DIR"
COPYFILE_DISABLE=1 tar \
  --no-xattrs \
  --no-mac-metadata \
  --exclude=".git" \
  --exclude="venv-mcp-broker" \
  --exclude="config/broker.private.yaml" \
  --exclude="var/coverage/*" \
  --exclude="var/quality/*" \
  --exclude="var/test-logs/*" \
  -C "$ROOT" \
  -cf "$ARCHIVE_PATH" \
  .
tar -xf "$ARCHIVE_PATH" -C "$CLONE_DIR"

(cd "$CLONE_DIR" && HOME="$HOME_DIR" make config-init RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$CLONE_DIR" && HOME="$HOME_DIR" make setup RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$CLONE_DIR" && HOME="$HOME_DIR" make config-validate RUNTIME_ROOT="$RUNTIME_ROOT")
(cd "$CLONE_DIR" && HOME="$HOME_DIR" make broker-smoke RUNTIME_ROOT="$RUNTIME_ROOT")

PRIVATE_PATH_MARKER="/""Users/"
if grep -R "$PRIVATE_PATH_MARKER" "$CLONE_DIR/README.md" "$CLONE_DIR/docs" "$CLONE_DIR/config" "$CLONE_DIR/scripts" >/dev/null 2>&1; then
  printf "release smoke found a private path marker\n" >&2
  exit 1
fi

printf "release_smoke=true work_dir=%s runtime_root=%s\n" "$WORK_DIR" "$RUNTIME_ROOT"
