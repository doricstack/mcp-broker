# Troubleshooting

Use this guide when the broker daemon, client shim, or an upstream MCP does not respond. Run runtime actions through Makefile targets so config paths, socket paths, and broker-owned cleanup stay centralized.

Start with:

```bash
make doctor
make broker-status
```

If either command reports stale resources, a failed upstream, or a missing command, fix that condition before retrying client wiring.

If this is a first-time public checkout, return to the Clone-To-Running Path in
`docs/adoption-guide.md` and confirm each command passes before debugging a
client-specific symptom.

When a client uses compact broker tools, `/mcp` shows only the single broker
entry. Call `broker_status` from the client, or run
`make profile-validation PROFILE=<profile>`, to inspect and validate which
upstreams the selected profile can see. `broker_status` includes auth state,
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
- `broker_search_tools` returns a `skipped_upstreams` entry for one upstream.
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

Use `broker_status` after an auth failure. `auth_state` reports
`unauthenticated` for auth-shaped failures and `unknown` when the broker has no
passive signal. `auth_probe` reports `credentials_missing` when configured env
or secret-file sources are absent, `credentials_present` when those sources
exist, `oauth_refresh_expired` when a configured OAuth token file has an expired
refresh-token timestamp, `auth_repair_configured` when only a repair setup tool
is configured, or `none` when no passive auth source exists.
`auth_repair_attempts`, `auth_repair_successes`, and `auth_repair_failures` show
whether a configured repair tool ran after a matching upstream error.

## Long Upstream Calls

Symptoms:
- A large draft, export, notebook, or report call times out while smaller calls to the same upstream pass.
- The upstream stays healthy, but the broker returns `upstream_timeout`.
- Logs show `upstream.call` for the slow tool followed by a failed `tools/call`.

Recovery:

```yaml
upstreams:
  mail-writer:
    health:
      call_timeout_seconds: 60
    tool_timeouts:
      create-draft-email: 300
```

`health.call_timeout_seconds` remains the default for the upstream. `tool_timeouts` overrides only the named upstream-local tools after the broker removes the upstream prefix. For example, a client call to `mail-writer.create-draft-email` checks `create-draft-email`.

Use this for slow mutating operations instead of raising the entire upstream timeout. Small status and discovery calls should still fail fast.

## Profile Denials

Symptoms:
- `tools/list` returns fewer tools than expected.
- A mutating upstream is hidden from the Codex or Claude profile.
- `tools/call` rejects a namespaced tool because the selected profile is not allowed to use that upstream.

Checks:

```bash
make tools-count PROFILE=codex
make tools-count PROFILE=claude
make tools-count PROFILE=agy
make tools-count PROFILE=protected
make profile-validation PROFILE=codex
make codex-claude-discovery-parity
```

Expected result: Codex, Claude, and AGY default profiles expose compact broker tools and read-heavy shared upstreams only. Protected write-capable upstreams stay behind the protected profile unless the profile allowlist names them.

Fix profile exposure in `config/broker.private.yaml` only after confirming:
- The upstream mode is correct.
- `mutating: true` is set for write-capable upstreams.
- The profile has an explicit `allow_mutating_upstreams` entry when needed.
- Each enabled profile-visible upstream has a safe `smoke` probe.
- `make quality-gate` and `make broker-smoke` pass after the change.

## AGY Shows Broker Disabled

Symptoms:
- `agy mcp list` shows the broker entry as disabled.
- The message says MCP servers are disabled because the folder is untrusted.

Checks:

```bash
agy mcp list
make agy-facade-smoke
make agy-profile-validation
```

If the Make targets pass, the broker config is valid. Trust the workspace in
AGY CLI, restart AGY, then rerun `agy mcp list`.

If AGY reports the broker as connected but cannot call any broker tools,
check that the AGY profile uses `broker_tool_name_style: snake` and that the
AGY client block sets `mcp_allowed_servers` to the broker entry name. AGY
should then call the broker status facade as `mcp_mcp-broker_broker_status`.
