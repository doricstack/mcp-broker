#!/bin/sh
set -eu

# Raise the file-descriptor soft limit before launching. The broker multiplexes
# many upstream subprocess pipes across clients; the container default can be too
# low and surfaces as "Too many open files" / dropped transports. Best-effort:
# skip silently if the container's hard limit is below the requested value.
ulimit -n "${MCP_BROKER_MAX_OPEN_FILES:-8192}" 2>/dev/null || true

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec mcp-broker stdio \
  --runtime-root "${MCP_BROKER_RUNTIME_ROOT:-/var/lib/mcp-broker}" \
  --socket-path "${MCP_BROKER_SOCKET:-/tmp/mcp-broker.sock}" \
  --config "${MCP_BROKER_CONFIG:-/etc/mcp-broker/broker.yaml}" \
  --profile "${MCP_BROKER_PROFILE:-docker}" \
  --init-if-missing \
  --ready-attempts "${MCP_BROKER_DOCKER_READY_ATTEMPTS:-50}"
