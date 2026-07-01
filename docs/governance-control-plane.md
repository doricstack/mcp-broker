# Governance Control Plane

`mcp-broker` does not need a hosted service to support enterprise governance.
Phase 2 defines publishable documents and local simulation rules first. The
local broker still owns execution, upstream startup, profile gates, client
rendering, status, and rollback on the engineer's machine.

## Governance Bundle Documents

Desired state is split into five publishable documents. They can be reviewed,
versioned, signed, mirrored through an internal artifact store, and validated by
the broker without running upstream tools centrally.

### Profile Bundle

The profile bundle defines client-visible behavior:

- profile names
- compact broker facade settings
- maximum exposed tools
- upstream exposure lists
- mutating-upstream allowlists
- broker tool name style

It must not contain local client config paths, account names, OAuth state,
runtime sockets, or private upstream inventory.

### Upstream Catalog Bundle

The upstream catalog bundle defines approved upstream templates:

- upstream identifiers and display names
- transport class
- command and argument templates
- purpose, tags, mutating flags, and lifecycle mode
- safe smoke-probe shape
- required environment variable names

It may name environment variables. It must not contain secret values. A catalog
entry is data only; the local broker decides whether a local private config maps
that entry to a real upstream.

### Policy Bundle

The policy bundle defines guardrails:

- `approval_required`
- `allow_remote_code_execution`
- `mutating_upstreams_require_allowlist`
- profile exposure rules
- redaction requirements
- rollback and break-glass requirements

The safe default is `approval_required: true`,
`allow_remote_code_execution: false`, and
`mutating_upstreams_require_allowlist: true`.

### Rollout Bundle

The rollout bundle defines how a version moves through a fleet:

- channels
- canary cohorts
- staged rollout rings
- required health gates
- rollback triggers
- operator approval points

The rollout document does not push config by itself. It gives the local broker
and offline simulator a plan to evaluate.

### Compatibility Bundle

The compatibility bundle defines version constraints:

- broker version range
- config schema version range
- required features
- deprecated feature flags
- compatibility rejection reasons

Compatibility rejection must happen before apply. A broker that cannot prove
compatibility must refuse the bundle.

## Local Execution Boundary

Execution stays local. The control-plane contract:

- does not run upstream tools centrally
- does not accept inbound remote tool calls
- does not start a remote listener
- does not move OAuth, browser, filesystem, or database state off the machine
- does not write client config without local approval

The local broker validates governance documents, stages desired state, applies
approved changes, reports status, and performs rollback through local runtime
state.

## Offline Control-Plane Simulation

Phase 2 uses local simulation only. The simulator should load the five
publishable documents, then evaluate:

- canary selection
- staged rollout ordering
- approval decisions
- compatibility rejection
- rollback decisions
- health gate outcomes

The simulator is not a hosted service. It is a deterministic local proof path
for enterprise governance behavior before any shared infrastructure is designed.

## Fleet Status Export

Fleet status is a redacted export derived from the local
`state/broker-status.json` snapshot:

```bash
mcp-broker fleet-status export --status-file ~/mcp/mcp-broker/state/broker-status.json
```

The export includes:

- broker identity: `broker_id`, `environment`, `bundle_version`,
  `schema_version`, and active profile names
- health: daemon status, start time, update time, and last request status
- counters: total requests and request errors
- upstream states: enabled flag, lifecycle state, transport, mode, mutating
  flag, auth state, restart count, and redacted last error

The export must not include local filesystem paths, socket paths, process IDs,
environment maps, account names, URLs, token values, credential values, OAuth
state, or private upstream configuration. It is a local JSON payload only. The
broker does not upload it and does not open an inbound status endpoint.

## Enterprise Adoption Path

An enterprise can publish the five documents from an internal artifact system,
then let each engineer clone the public repo, install the broker, and validate
the desired state locally. That keeps the repo useful for personal users while
giving teams a governance contract they can automate around.
