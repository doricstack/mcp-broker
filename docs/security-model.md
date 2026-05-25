# mcp-broker Security Model

## Principle

Central broker, isolated upstream state.

## State Layout

```text
~/mcp/mcp-broker/state/upstreams/<name>/
~/mcp/mcp-broker/secrets/
~/mcp/mcp-broker/renders/
~/mcp/mcp-broker/backups/<client>/
```

Each upstream gets its own state directory. This is required for browser profiles, OAuth cookies, local caches, and auth material.

## Credential Rules

- No secrets in the repo.
- No secrets in example config.
- No tokens in logs.
- Structured log writes redact env maps, token-like keys, credentials, access IDs, URLs, and filesystem paths before serialization.
- Secrets are read from `secrets_dir` or environment variables named in config.
- Per-upstream env config maps child-process env names to host env names, for example `UPSTREAM_API_TOKEN: MCP_BROKER_UPSTREAM_TOKEN`.
- Config validation rejects env entries that are not variable names, so repo config stores names only.
- The broker must not print command env values.

## Remote Broker Access

The current daemon listens only on the configured Unix socket. Before this repo
adds any TCP, HTTP, or other remote broker listener, that listener must enforce
`broker.remote_auth`.

`broker.remote_auth.required` must remain `true`. Enabling the remote auth
policy requires either `token_env` or `token_file`, both resolved from central
config and runtime secret storage. Remote broker requests must fail closed when
the token source is missing or invalid.

## Client Config Rendering

Runtime client config render definitions live in `config/broker.private.yaml` under `clients`.
`config/broker.example.yaml` is a generic public template and does not contain the current private upstream inventory.
Related client backup files also live in central config under `clients.<name>.backup_paths`.
Rendering is dry-run unless `CONFIG_RENDER_APPLY=1` is set on the Makefile target.
Dry-run writes the candidate client config under `~/mcp/mcp-broker/renders/` and does not touch Codex or Claude config files.
`make config-backup CLIENT=<client>` copies the configured target and related backup paths without rendering or writing client config.
Applied renders create a backup under `~/mcp/mcp-broker/backups/<client>/` before writing the configured target file.
Rollback restores the latest backup for the selected client.

## Secret Inputs

Upstreams can resolve secret values from host environment names under `upstreams.<name>.env` or from runtime secret files under `upstreams.<name>.env_files`.
Runtime secret files belong under `~/mcp/mcp-broker/secrets/` and are not stored in the source repo.
Use `make secret-import-env SECRET_NAME=<name>` to copy an existing shell secret into the runtime secret store with mode `600`.
LaunchAgent-managed upstreams should use `env_files` because launchd does not inherit interactive shell secrets.

## LaunchAgent Gate

`scripts/install-launchagent.sh` is dry-run by default.
It runs `make broker-smoke` before writing any LaunchAgent file.
If smoke fails, install exits with the smoke status and writes nothing.
Dry-run writes the candidate plist under `~/mcp/mcp-broker/renders/`.
Apply mode writes `~/Library/LaunchAgents/com.mcp-broker.agent.plist` only after smoke passes.
The label is generic and the ProgramArguments include `--config` with the central broker config path.
If a LaunchAgent plist already exists, apply mode backs it up under `~/mcp/mcp-broker/backups/launchagent/` before writing the replacement.

## Client Profiles

Broker config supports client profiles:
- `codex`
- `claude`
- `gemini`
- `manual-test`
- `maintenance`

Profiles can allow or deny tool prefixes and mutating tools.
Gemini is currently an exposure profile only; this repo does not render a Gemini client config format yet.

Mutating upstreams must declare `mutating: true` in central config. Any profile that exposes a mutating upstream must list that upstream name under `profiles.<profile>.allow_mutating_upstreams`; config load fails without the allowlist entry. Runtime tool advertisement enforces the same check so hand-built config objects cannot bypass the profile gate.
