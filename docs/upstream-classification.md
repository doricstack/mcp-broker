# Upstream Classification

This document defines generic upstream classification rules for public users.
It does not contain a local user's private MCP inventory. See
`docs/upstream-compatibility-matrix.md` for the example-config matrix.

## Public Example Records

The public config includes these disabled examples to show the contract shape:

- `example-store`
- `example-python`
- `example-env-auth`
- `example-file-auth`
- `example-request-meta-auth`
- `example-http`
- `example-mutating`

## Shared Candidates

Use `shared` only when the upstream is safe for multiple concurrent sessions.

| Upstream Type | Initial Mode | Reason |
|---|---|---|
| Stateless read-only stdio server | `shared` after smoke test | No per-session state, write path, browser state, or credential mutation. |
| Local reference lookup server | `shared` after smoke test | Deterministic read-only responses can be reused across sessions. |
| Remote HTTP read-only MCP | `shared` after auth and timeout smoke test | No local process is owned, but remote auth and health still need policy. |

## Protected Shared Candidates

Use `shared` with `serialize_calls: true` only when one shared account or token
is intended and concurrent calls can collide.

| Upstream Type | Initial Mode | Risk |
|---|---|---|
| OAuth-backed SaaS connector | `shared` plus `serialize_calls: true` | Shared account state and write operations require serialization. |
| Token-backed SaaS connector with writes | `shared` plus `serialize_calls: true` | Mutating operations require profile allowlists and redacted secrets. |
| Local notes or knowledge-base writer | `shared` plus `serialize_calls: true` | Writes must be serialized to avoid conflicting edits. |

## Session-Isolated Candidates

Use `per_session` when state, roots, credentials, or browser context differ by
task.

| Upstream Type | Initial Mode | Risk |
|---|---|---|
| Browser automation connector | `per_session` | Browser context and interactive state are session-scoped. |
| Filesystem connector | `per_session` | Root authorization differs by project and user intent. |
| Database connector | `per_session` and protected | Credentials and writes need a narrow session boundary. |
| Cloud deploy or infrastructure connector | `per_session` and protected | Remote mutations must not be shared by default. |
| Project-specific connector | `per_session` or separate record | Account, project, or root selection must stay explicit. |

## Disabled Compatibility Records

Use `disabled` for imported MCP records until they have:

- A smoke probe.
- A state directory under the runtime root.
- An explicit profile list.
- An auth source that stores names or secret-file paths, never secret values.
- `mutating: true` plus profile allowlists when the upstream can write.

Duplicate display-name records stay source-specific until migration smoke tests
prove package, state, root, credential, and mutation compatibility.
