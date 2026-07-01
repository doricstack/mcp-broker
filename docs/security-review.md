# Security Review

This review defines the current security posture for private `mcp-broker`
runtime use and the gates required before broader use.

## Secrets

Secret values must not be committed. Config may name where secrets come from,
but it must not store the values.

Allowed inputs:
- `env`: maps child process variable names to host environment variable names.
- `env_files`: maps child process variable names to files under `secrets_dir`.
- `secrets_dir`: runtime-only secret storage under `$HOME/mcp/mcp-broker/secrets`.

Rules:
- LaunchAgent-managed upstreams should use `env_files`.
- Runtime secret files must use mode `600`.
- Logs must redact env maps, token-like keys, credentials, URLs, and local paths.
- Public examples must not contain private hostnames, account names, tokens, or local roots.

## OAuth State

OAuth-backed upstreams keep account state inside broker-owned runtime state, not
inside per-client MCP processes.

Rules:
- OAuth-backed upstreams that can mutate external state must use `mutating: true`.
- Shared OAuth-backed upstreams must use `shared` plus `serialize_calls: true` when concurrent writes can collide.
- Profiles exposing those upstreams must list them in `allow_mutating_upstreams`.
- Default Codex, Claude, and AGY profiles must not expose protected OAuth upstreams.

Current protected OAuth surfaces:
- `workspace-writer`
- `mail-writer`
- `notes-writer`

## Browser State

Browser-backed MCPs can carry cookies, local storage, downloads, and active
login sessions. Treat browser state as user account state.

Rules:
- Browser-state upstreams start as `per_session`.
- Browser roots must be under broker-owned runtime state.
- No browser profile path belongs in a public example.
- Sharing requires a live test proving cleanup, isolation, and no cross-session state bleed.

## Filesystem Roots

Filesystem MCPs are high-risk because their allowed roots determine what a
client can read or change.

Rules:
- Filesystem upstreams start as `per_session`.
- Every filesystem upstream that can write files must use `mutating: true`.
- Root paths must be file-backed in private config and reviewed before exposure.
- Public examples must use placeholders or disabled example roots only.
- Codex, Claude, and AGY default profiles must not expose filesystem roots.

## Database Access

Database MCPs can read private data and can mutate durable state.

Rules:
- Database upstreams start as `per_session`.
- Database URLs must be referenced by environment variable name only.
- Database MCPs that can write must use `mutating: true`.
- Profiles exposing database upstreams must list them in `allow_mutating_upstreams`.
- Remote database upstreams need live smoke tests for timeout, auth failure, and rollback behavior before exposure.

## Required Gates

Before enabling or exposing an upstream, confirm its row in `docs/upstream-compatibility-matrix.md` matches the central config for mode, transport, auth source, mutation risk, and profile exposure.

Run these gates before applying client config, changing LaunchAgent config, or
enabling a protected upstream:

```bash
make quality-gate
make doctor
make broker-smoke
make tools-count PROFILE=codex
make tools-count PROFILE=protected
```

Before commit:

```bash
make precommit
```

Before applying client config:

```bash
make config-backup CLIENT=<client>
make config-render CLIENT=<client> CONFIG_RENDER_APPLY=0
make config-render CLIENT=<client> CONFIG_RENDER_APPLY=1
```

Rollback path:

```bash
make config-rollback CLIENT=<client>
make doctor
```
