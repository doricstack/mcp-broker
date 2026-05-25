#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${MCP_BROKER_LINUX_SMOKE_IMAGE:-python:3-bookworm}"
WORK_DIR="${MCP_BROKER_LINUX_SMOKE_DIR:-}"

usage() {
  cat <<'USAGE'
usage: linux-container-smoke.sh [--help]

Runs the public setup path inside a Linux container using the current working
tree contents, excluding local runtime, venv, git metadata, and private config.

Environment:
  MCP_BROKER_LINUX_SMOKE_IMAGE   Container image, default: python:3-bookworm
  MCP_BROKER_LINUX_SMOKE_DIR     Optional existing work directory
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

command -v docker >/dev/null 2>&1 || {
  printf "docker is required for linux-container-smoke\n" >&2
  exit 2
}

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-linux-smoke.XXXXXX")"
fi

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

ARCHIVE_PATH="$WORK_DIR/source.tar"
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

docker run --rm \
  -v "$ARCHIVE_PATH:/tmp/source.tar:ro" \
  "$IMAGE" \
  bash -lc '
    set -euo pipefail
    apt-get update
    apt-get install -y --no-install-recommends make
    mkdir -p /workspace /tmp/home /tmp/runtime
    tar -xf /tmp/source.tar -C /workspace
    cd /workspace
    HOME=/tmp/home make config-init RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    HOME=/tmp/home make setup RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    HOME=/tmp/home make config-validate RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    HOME=/tmp/home make broker-smoke RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    HOME=/tmp/home make systemd-install RUNTIME_ROOT=/tmp/runtime CONFIG_PATH=/workspace/config/broker.private.yaml PYTHON_BIN=python3
  '

printf "linux_container_smoke=true image=%s\n" "$IMAGE"
