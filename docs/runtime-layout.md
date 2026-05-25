# Runtime Layout

Runtime root:

```text
~/mcp/mcp-broker/
  config/
  logs/
  run/
    sockets/
    upstreams/
  secrets/
  sockets/
  state/
    broker-status.json
    upstreams/
      example-store/
      example-http/
      example-mutating/
```

The repo owns source and tests. The runtime root owns machine-specific state.

`make doctor` creates the base runtime directories, runs the broker-owned
runtime reaper, verifies that the central config file exists, and fails when an
enabled stdio upstream command is missing or not executable. Disabled upstreams
and non-stdio upstreams are skipped. It does not start the broker.

Runtime ownership metadata is file-backed under `run/upstreams/*.json` and
`run/sockets/*.json`. `make broker-reap` removes stale broker-owned pidfiles,
removes stale broker-owned sockets, and kills orphaned broker-owned process
groups whose recorded broker PID no longer exists. If an upstream parent PID has
already exited but the recorded process group still has child members, the reaper
kills that process group before removing the pidfile.

Broker daemon structured logs are newline-delimited JSON at
`logs/broker.jsonl`. Each record includes `ts`, `level`, `event`, and `pid`.
Daemon events cover lifecycle start/stop, handled socket requests, and upstream
events: `upstream.start`, `upstream.ready`, `upstream.call`,
`upstream.timeout`, `upstream.stop`, `upstream.kill`, `upstream.restart`,
`upstream.backoff`, and `upstream.disabled`. Upstream events include the
`upstream` name and event-specific fields such as `method`, `tool_name`,
`timeout_seconds`, `state`, `signal`, and `restart_count`.

Log values are redacted before write for env maps, tokens, credentials, access
IDs, URLs, and filesystem paths.

Broker daemon metrics are file-backed at `state/broker-status.json`. The daemon
writes the snapshot at start, after each handled socket request, and during
shutdown. The snapshot includes daemon status, PID, socket path, start and update
timestamps, request and request-error counters, last request method and status,
and the same per-upstream health map returned by `broker/health`, including
auth-repair counters when a configured repair path has run.
