#!/bin/bash
set -euo pipefail

runtime_root="${MCP_BROKER_RUNTIME_ROOT:-$HOME/mcp/mcp-broker}"
mkdir -p \
  "$runtime_root/logs" \
  "$runtime_root/run" \
  "$runtime_root/run/sockets" \
  "$runtime_root/run/upstreams" \
  "$runtime_root/secrets" \
  "$runtime_root/sockets" \
  "$runtime_root/state/upstreams"

printf 'mcp-broker runtime ready: %s\n' "$runtime_root"
