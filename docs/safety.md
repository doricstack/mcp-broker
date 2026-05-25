# Safety Guide

`mcp-broker` reduces local MCP sprawl, but it does not make unsafe upstreams safe. Treat every upstream as code with access to some combination of local files, credentials, browsers, databases, and remote APIs.

The main broker-mediated risk areas are mutating tools, OAuth state, browser state, filesystem roots, database URLs, and per-profile allowlists.

## Mutating Tools

Mark write-capable upstreams with `mutating: true`.

Profiles must opt in through `allow_mutating_upstreams`. This prevents a write-capable upstream from appearing in a chat-facing profile by accident.

Recommended pattern:

```yaml
upstreams:
  example-mutating:
    enabled: false
    mutating: true

profiles:
  codex:
    allow_mutating_upstreams: []
```

Enable write paths only after a safe smoke probe and a human review of the exposed tools.

## OAuth State

OAuth-backed upstreams should store token state under the runtime root, not in the repo.

Default runtime:

```text
$HOME/mcp/mcp-broker/
```

Use file-backed secrets or env var names. Do not store token values in YAML examples, tests, docs, logs, or issue templates.

Passive status probes must not open a browser. Browser auth repair is an explicit configured action triggered by matching auth errors.

## Browser State

Browser automation upstreams should start as `per_session` unless you have tested parallel sessions against the same browser profile.

Use shared browser state only when the upstream documents that concurrent sessions are safe and the profile is meant to share cookies, local storage, downloads, and browser context.

## Filesystem Roots

Filesystem upstreams should use narrow roots. Project-wide roots are safer than home-directory roots. Home-directory roots are safer than full-disk roots.

Never put personal paths in public config. Use placeholders and document the choice:

```yaml
args:
  - "{client.cwd}"
```

## Database URLs

Database upstreams should be protected and profile-limited.

Use read-only credentials for normal profiles. Write credentials need a separate profile and an explicit smoke probe that does not mutate production data.

Never log full database URLs. Redact usernames, passwords, hosts that identify private infrastructure, and query strings that contain tokens.

## Per-Profile Allowlists

Profiles are the broker safety boundary.

Use these defaults:

- Small `max_tools`.
- `compact_tools_enabled: true`.
- No mutating upstream allowlist until reviewed.
- Protected upstreams hidden from default chat profiles.
- Separate maintenance profile for broad inspection tools.

## Status And Auditing

Use `broker.status` to inspect exposed upstreams without starting them. The status response should show enabled state, exposure state, mode, transport, mutation flag, passive auth state, runtime state, PID when running, restart count, and last error.

Runtime logs belong under:

```text
$HOME/mcp/mcp-broker/logs/
```

Repo quality reports belong under:

```text
var/quality/
```

Do not place logs, token dumps, auth JSON, or quality reports in the repo root.
