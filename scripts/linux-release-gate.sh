#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${MCP_BROKER_LINUX_RELEASE_GATE_IMAGE:-python:3.13-bookworm}"
WORK_DIR="${MCP_BROKER_LINUX_RELEASE_GATE_DIR:-}"

usage() {
  cat <<'USAGE'
usage: linux-release-gate.sh [--help]

Runs the same release gate used by the PyPI workflow inside a Linux container.
The source tree is copied through a public-safe archive, then initialized as a
synthetic git checkout so git-aware release tests match GitHub Actions without
copying host git metadata into the container.

Environment:
  MCP_BROKER_LINUX_RELEASE_GATE_IMAGE   Container image, default: python:3.13-bookworm
  MCP_BROKER_LINUX_RELEASE_GATE_DIR     Optional existing work directory
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
  printf "docker is required for linux-release-gate\n" >&2
  exit 2
}

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-linux-release-gate.XXXXXX")"
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
SOURCE_LIST_PATH="$WORK_DIR/source-files.txt"
TAR_CREATE_OPTIONS=()
if tar_option_supported "--no-xattrs"; then
  TAR_CREATE_OPTIONS+=(--no-xattrs)
fi
if tar_option_supported "--no-mac-metadata"; then
  TAR_CREATE_OPTIONS+=(--no-mac-metadata)
fi

(
  cd "$ROOT"
  git ls-files -co --exclude-standard -z >"$SOURCE_LIST_PATH"
  COPYFILE_DISABLE=1 tar \
    "${TAR_CREATE_OPTIONS[@]}" \
    --null \
    -T "$SOURCE_LIST_PATH" \
    -cf "$ARCHIVE_PATH"
)

docker run --rm \
  -v "$ARCHIVE_PATH:/tmp/source.tar:ro" \
  "$IMAGE" \
  bash -lc '
    set -euo pipefail
    apt-get update
    apt-get install -y --no-install-recommends git make
    mkdir -p /workspace /tmp/home/.config /tmp/runner-temp/mcp-broker
    tar -xf /tmp/source.tar -C /workspace
    cd /workspace
    export HOME=/tmp/home
    export XDG_CONFIG_HOME=/tmp/home/.config
    export RUNNER_TEMP=/tmp/runner-temp
    export GITHUB_ACTIONS=true
    git init -q
    git config --global --add safe.directory /workspace
    git add .
    make setup RUNTIME_ROOT="$RUNNER_TEMP/mcp-broker" PYTHON_BIN=python3
    make release-gate RUNTIME_ROOT="$RUNNER_TEMP/mcp-broker" PYTHON_BIN=python3
  '

printf "linux_release_gate=true image=%s\n" "$IMAGE"
