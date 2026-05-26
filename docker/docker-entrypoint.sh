#!/bin/sh
set -eu

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
