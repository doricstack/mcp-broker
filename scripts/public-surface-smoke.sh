#!/bin/bash
set -euo pipefail

PUBLIC_SURFACE_VERSION="${PUBLIC_SURFACE_VERSION:-}"
PUBLIC_SURFACE_REQUIRE_NPM="${PUBLIC_SURFACE_REQUIRE_NPM:-0}"
PUBLIC_SURFACE_REQUIRE_DOCKER="${PUBLIC_SURFACE_REQUIRE_DOCKER:-0}"
PYPI_PROJECT_NAME="${PYPI_PROJECT_NAME:-}"
PACKAGE_COMMAND_NAME="${PACKAGE_COMMAND_NAME:-}"
PACKAGE_CLIENT_COMMAND_NAME="${PACKAGE_CLIENT_COMMAND_NAME:-}"
PACKAGE_DAEMON_COMMAND_NAME="${PACKAGE_DAEMON_COMMAND_NAME:-}"
GITHUB_TAG_SOURCE_TARBALL_URL="${GITHUB_TAG_SOURCE_TARBALL_URL:-}"
HOMEBREW_FORMULA_REF="${HOMEBREW_FORMULA_REF:-}"
MCP_REGISTRY_NAME="${MCP_REGISTRY_NAME:-}"
MCP_REGISTRY_SEARCH_URL="${MCP_REGISTRY_SEARCH_URL:-}"
NPM_PACKAGE_NAME="${NPM_PACKAGE_NAME:-}"
DOCKER_RELEASE_IMAGE="${DOCKER_RELEASE_IMAGE:-}"
WORK_DIR="${PUBLIC_SURFACE_WORK_DIR:-}"
KEEP_WORK_DIR="${PUBLIC_SURFACE_KEEP:-0}"

usage() {
  cat <<'USAGE'
usage: public-surface-smoke.sh [--help]

Downloads public mcp-broker artifacts into a temporary directory and verifies
the install surface a user would receive.

Environment:
  PUBLIC_SURFACE_VERSION          Version to verify
  PUBLIC_SURFACE_REQUIRE_NPM      Set to 1 when NPM must exist
  PUBLIC_SURFACE_REQUIRE_DOCKER   Set to 1 when Docker image must exist
  PUBLIC_SURFACE_WORK_DIR         Optional existing work directory
  PUBLIC_SURFACE_KEEP             Set to 1 to keep the work directory
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

command -v python3 >/dev/null 2>&1 || { printf "python3 is required\n" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { printf "curl is required\n" >&2; exit 2; }
command -v tar >/dev/null 2>&1 || { printf "tar is required\n" >&2; exit 2; }
command -v pipx >/dev/null 2>&1 || { printf "pipx is required\n" >&2; exit 2; }
command -v uvx >/dev/null 2>&1 || { printf "uvx is required\n" >&2; exit 2; }

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    printf "%s is required\n" "$name" >&2
    exit 2
  fi
}

if [[ -z "$PUBLIC_SURFACE_VERSION" ]]; then
  printf "PUBLIC_SURFACE_VERSION is required\n" >&2
  exit 2
fi

require_env PYPI_PROJECT_NAME
require_env PACKAGE_COMMAND_NAME
require_env PACKAGE_CLIENT_COMMAND_NAME
require_env PACKAGE_DAEMON_COMMAND_NAME
require_env GITHUB_TAG_SOURCE_TARBALL_URL
require_env HOMEBREW_FORMULA_REF
require_env MCP_REGISTRY_NAME
require_env MCP_REGISTRY_SEARCH_URL
if [[ "$PUBLIC_SURFACE_REQUIRE_NPM" == "1" ]]; then
  require_env NPM_PACKAGE_NAME
fi
if [[ "$PUBLIC_SURFACE_REQUIRE_DOCKER" == "1" ]]; then
  require_env DOCKER_RELEASE_IMAGE
fi

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-public-surface.XXXXXX")"
fi

cleanup() {
  if [[ "$KEEP_WORK_DIR" != "1" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

printf "public_surface_smoke_start version=%s work_dir=%s\n" "$PUBLIC_SURFACE_VERSION" "$WORK_DIR"

PYPI_VENV="$WORK_DIR/pypi-venv"
python3 -m venv "$PYPI_VENV"
PYTHONPATH="" "$PYPI_VENV/bin/python" -m pip install --upgrade pip >/dev/null
PYTHONPATH="" "$PYPI_VENV/bin/python" -m pip install "$PYPI_PROJECT_NAME==$PUBLIC_SURFACE_VERSION" >/dev/null
PYTHONPATH="" "$PYPI_VENV/bin/$PACKAGE_COMMAND_NAME" --help >/dev/null
PYTHONPATH="" "$PYPI_VENV/bin/$PACKAGE_CLIENT_COMMAND_NAME" --help >/dev/null
PYTHONPATH="" "$PYPI_VENV/bin/$PACKAGE_DAEMON_COMMAND_NAME" --help >/dev/null
printf "public_surface_pypi=true version=%s\n" "$PUBLIC_SURFACE_VERSION"

PIPX_HOME="$WORK_DIR/pipx-home" PIPX_BIN_DIR="$WORK_DIR/pipx-bin" \
  PYTHONPATH="" pipx run --spec "$PYPI_PROJECT_NAME==$PUBLIC_SURFACE_VERSION" "$PACKAGE_COMMAND_NAME" --help >/dev/null
UV_TOOL_DIR="$WORK_DIR/uv-tools" UV_CACHE_DIR="$WORK_DIR/uv-cache" \
  PYTHONPATH="" uvx --from "$PYPI_PROJECT_NAME==$PUBLIC_SURFACE_VERSION" "$PACKAGE_COMMAND_NAME" --help >/dev/null
printf "public_surface_tool_runners=true version=%s\n" "$PUBLIC_SURFACE_VERSION"

SOURCE_TARBALL="$WORK_DIR/github-source.tar.gz"
SOURCE_DIR="$WORK_DIR/github-source"
curl -fsSL \
  "$GITHUB_TAG_SOURCE_TARBALL_URL" \
  -o "$SOURCE_TARBALL"
mkdir -p "$SOURCE_DIR"
tar -xzf "$SOURCE_TARBALL" -C "$SOURCE_DIR" --strip-components 1
HOME="$WORK_DIR/github-home" \
XDG_CONFIG_HOME="$WORK_DIR/github-home/.config" \
  make -C "$SOURCE_DIR" setup RUNTIME_ROOT="$WORK_DIR/github-runtime" >/dev/null
HOME="$WORK_DIR/github-home" \
XDG_CONFIG_HOME="$WORK_DIR/github-home/.config" \
  make -C "$SOURCE_DIR" config-validate RUNTIME_ROOT="$WORK_DIR/github-runtime" >/dev/null
printf "public_surface_github_release=true version=%s\n" "$PUBLIC_SURFACE_VERSION"

if command -v brew >/dev/null 2>&1; then
  brew update --force --quiet >/dev/null
  HOMEBREW_CACHE="$WORK_DIR/homebrew-cache" brew fetch --formula "$HOMEBREW_FORMULA_REF" >/dev/null
  brew info --formula "$HOMEBREW_FORMULA_REF" | grep -q "$PUBLIC_SURFACE_VERSION"
  if brew list --formula "$PYPI_PROJECT_NAME" >/dev/null 2>&1; then
    brew upgrade "$HOMEBREW_FORMULA_REF" >/dev/null || \
      brew list --formula --versions "$PYPI_PROJECT_NAME" | grep -q " $PUBLIC_SURFACE_VERSION"
  else
    brew install "$HOMEBREW_FORMULA_REF" >/dev/null
  fi
  brew list --formula --versions "$PYPI_PROJECT_NAME" | grep -q " $PUBLIC_SURFACE_VERSION"
  "$(brew --prefix "$HOMEBREW_FORMULA_REF")/bin/$PACKAGE_COMMAND_NAME" --help >/dev/null
  brew test "$HOMEBREW_FORMULA_REF" >/dev/null
  printf "public_surface_homebrew=true version=%s\n" "$PUBLIC_SURFACE_VERSION"
else
  printf "public_surface_homebrew=missing_brew\n" >&2
  exit 2
fi

PUBLIC_SURFACE_VERSION="$PUBLIC_SURFACE_VERSION" MCP_REGISTRY_NAME="$MCP_REGISTRY_NAME" MCP_REGISTRY_SEARCH_URL="$MCP_REGISTRY_SEARCH_URL" PYPI_PROJECT_NAME="$PYPI_PROJECT_NAME" python3 - <<'PY'
import json
import os
import sys
import urllib.request

name = os.environ["MCP_REGISTRY_NAME"]
version = os.environ["PUBLIC_SURFACE_VERSION"]
project = os.environ["PYPI_PROJECT_NAME"]
url = os.environ["MCP_REGISTRY_SEARCH_URL"]
with urllib.request.urlopen(url, timeout=30) as response:
    payload = json.load(response)

encoded = json.dumps(payload)
if name not in encoded or version not in encoded or project not in encoded:
    raise SystemExit(f"MCP Registry response missing {name} {version}")
sys.stdout.write(f"public_surface_mcp_registry=true version={version}\n")
PY

if [[ "$PUBLIC_SURFACE_REQUIRE_NPM" == "1" ]]; then
  command -v npm >/dev/null 2>&1 || { printf "npm is required\n" >&2; exit 2; }
  command -v npx >/dev/null 2>&1 || { printf "npx is required\n" >&2; exit 2; }
  npm view "$NPM_PACKAGE_NAME@$PUBLIC_SURFACE_VERSION" version repository dist-tags --json >/dev/null
  npm_config_cache="$WORK_DIR/npm-cache" npx -y "$NPM_PACKAGE_NAME@$PUBLIC_SURFACE_VERSION" --help >/dev/null
  printf "public_surface_npm=true package=%s version=%s\n" "$NPM_PACKAGE_NAME" "$PUBLIC_SURFACE_VERSION"
fi

if [[ "$PUBLIC_SURFACE_REQUIRE_DOCKER" == "1" ]]; then
  command -v docker >/dev/null 2>&1 || { printf "docker is required\n" >&2; exit 2; }
  docker buildx imagetools inspect "$DOCKER_RELEASE_IMAGE" >/dev/null
  DOCKER_OUTPUT="$WORK_DIR/docker-tools-list.jsonl"
  printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"public-surface-smoke","version":"0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n' |
    docker run --rm -i "$DOCKER_RELEASE_IMAGE" >"$DOCKER_OUTPUT"
  grep -q '"tools"' "$DOCKER_OUTPUT"
  printf "public_surface_docker=true image=%s\n" "$DOCKER_RELEASE_IMAGE"
fi

printf "public_surface_smoke=true version=%s work_dir=%s\n" "$PUBLIC_SURFACE_VERSION" "$WORK_DIR"
