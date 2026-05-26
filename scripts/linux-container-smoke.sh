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

tar_option_supported() {
  local option="$1"
  local probe_dir
  probe_dir="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-tar-probe.XXXXXX")"
  if tar "$option" -cf /dev/null -C "$probe_dir" . >/dev/null 2>&1; then
    rm -rf "$probe_dir"
    return 0
  fi
  rm -rf "$probe_dir"
  return 1
}

ARCHIVE_PATH="$WORK_DIR/source.tar"
TAR_CREATE_OPTIONS=()
if tar_option_supported "--no-xattrs"; then
  TAR_CREATE_OPTIONS+=(--no-xattrs)
fi
if tar_option_supported "--no-mac-metadata"; then
  TAR_CREATE_OPTIONS+=(--no-mac-metadata)
fi
COPYFILE_DISABLE=1 tar \
  "${TAR_CREATE_OPTIONS[@]}" \
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
    mkdir -p /workspace /tmp/home/.config /tmp/runtime
    tar -xf /tmp/source.tar -C /workspace
    cd /workspace
    export HOME=/tmp/home
    export XDG_CONFIG_HOME=/tmp/home/.config
    make config-init RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    make setup RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    make config-validate RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    make broker-smoke RUNTIME_ROOT=/tmp/runtime PYTHON_BIN=python3
    make systemd-install RUNTIME_ROOT=/tmp/runtime CONFIG_PATH=/workspace/config/broker.private.yaml PYTHON_BIN=python3
  '

printf "linux_container_smoke=true image=%s\n" "$IMAGE"
