# Troubleshooting

Use this guide when the broker daemon, client shim, or an upstream MCP does not respond. Run runtime actions through Makefile targets so config paths, socket paths, and broker-owned cleanup stay centralized.

Start with:

```bash
make doctor
make broker-status
```

If either command reports stale resources, a failed upstream, or a missing command, fix that condition before retrying client wiring.

When a client uses compact broker tools, `/mcp` shows only the single broker
entry. Call `broker.status` from the client, or run
`make profile-validation PROFILE=<profile>`, to inspect and validate which
upstreams the selected profile can see. `broker.status` includes auth state,
passive auth probe state, session count, last error, and auth-repair counters
without starting auth flows. The validation target uses the `smoke` probes
configured in YAML and fails if any enabled profile-visible upstream lacks one.

## Zombie Or Orphan Processes

Symptoms:
- `make doctor` reports stale broker-owned pidfiles.
- `make doctor` reports broker-owned process IDs after daemon shutdown.
- A client request hangs after a broker crash or force quit.

Recovery:

```bash
make broker-stop
make broker-reap
make doctor
```

Expected result: `make doctor` reports no stale broker-owned resources.

If broker-owned process IDs remain after `make broker-reap`, do not restart clients yet. Fix the reaper path first, then rerun the same three commands. The broker must not start new upstreams while old broker-owned process groups remain alive.

## Socket Conflicts

Symptoms:
- The daemon refuses to start because the broker socket already exists.
- The client shim cannot connect to the configured socket.
- `make broker-status` reports no healthy daemon even though the socket file exists.

Recovery:

```bash
make broker-stop
make broker-reap
make doctor
make broker-status
```

Expected result: stale sockets are removed only when their owner process is gone. Live owned sockets stay in place.

If the socket remains conflicted, inspect the runtime state through broker-owned metadata, then fix the stale-socket check before applying any client config.

## Broken Upstream Commands

Symptoms:
- `make doctor` reports a missing enabled stdio upstream command.
- `make broker-smoke` fails while starting an upstream.
- `tools/list` fails for a profile that should expose that upstream.

Recovery:

```bash
make doctor
make broker-smoke
make tools-count PROFILE=codex
```

For protected upstreams, use:

```bash
make tools-count PROFILE=protected
```

Expected result: enabled stdio commands resolve from central config and disabled upstreams do not block doctor checks.

Fix the upstream record in `config/broker.private.yaml`. Do not patch source code to compensate for a bad local command path.

## Auth Failures

Symptoms:
- `broker.search_tools` returns a `skipped_upstreams` entry for one upstream.
- `make broker-smoke` fails with an auth or token error.
- A LaunchAgent-backed upstream works in an interactive shell but fails when the daemon owns it.
- An upstream returns a tool-level auth error naming an env var, for example `NLMCP_AUTH_TOKEN`.

Recovery:

```bash
make doctor
make secret-import-env SECRET_NAME=<name>
make broker-stop
make broker-reap
make broker-smoke
```

Expected result: LaunchAgent-managed secrets are file-backed under the runtime secrets directory, and logs redact credential names and values.

Keep secret values out of `config/broker.private.yaml`. Use `env` for host environment variable names or `env_files` for broker-owned runtime secret files. If the upstream requires per-call MCP metadata, map the secret through `request_meta`. If the upstream exposes browser setup auth, configure `auth_repair` so the broker can run that setup tool after a matching auth error and retry the original call.

Use `broker.status` after an auth failure. `auth_state` reports
`unauthenticated` for auth-shaped failures and `unknown` when the broker has no
passive signal. `auth_probe` reports `credentials_missing` when configured env
or secret-file sources are absent, `credentials_present` when those sources
exist, `auth_repair_configured` when only a repair setup tool is configured, or
`none` when no passive auth source exists. `auth_repair_attempts`,
`auth_repair_successes`, and `auth_repair_failures` show whether a configured
repair tool ran after a matching upstream error.

## Profile Denials

Symptoms:
- `tools/list` returns fewer tools than expected.
- A mutating upstream is hidden from the Codex or Claude profile.
- `tools/call` rejects a namespaced tool because the selected profile is not allowed to use that upstream.

Checks:

```bash
make tools-count PROFILE=codex
make tools-count PROFILE=claude
make tools-count PROFILE=gemini
make tools-count PROFILE=protected
make profile-validation PROFILE=codex
make codex-claude-discovery-parity
```

Expected result: Codex, Claude, and Gemini default profiles expose compact broker tools and read-heavy shared upstreams only. Protected write-capable upstreams stay behind the protected profile unless the profile allowlist names them.

Fix profile exposure in `config/broker.private.yaml` only after confirming:
- The upstream mode is correct.
- `mutating: true` is set for write-capable upstreams.
- The profile has an explicit `allow_mutating_upstreams` entry when needed.
- Each enabled profile-visible upstream has a safe `smoke` probe.
- `make quality-gate` and `make broker-smoke` pass after the change.
