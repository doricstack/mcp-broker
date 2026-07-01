# Shared Runtime Guardrails

`mcp-broker` is a local edge broker first. The shared hosted execution is not
implemented, and it must not be treated as an implied roadmap commitment until
the local product proves value and the governance contracts prove they can
control change safely.

Contract statement: shared hosted execution is not implemented.

## Current Boundary

The local edge broker remains the default execution boundary. Each engineer's
machine owns MCP client config, upstream startup, OAuth state, browser state,
runtime sockets, logs, deployment state, rollback, and profile validation.

There is no remote listener, no shared upstream execution, no hosted tool-call
endpoint, and no central process that runs an engineer's upstream MCP servers.
Phase 3 is a guardrail definition only.

## Preconditions

Shared hosted execution can be designed only after both proofs exist:

- Phase 1 value proof: plugin setup, clone-to-running setup, local deployment
  state, rollback, and profile validation work for real personal and team use.
- Phase 2 governance proof: signed desired-state bundles, redacted fleet
  status, local simulation, staged rollout, compatibility rejection, and
  approval decisions are proven without moving execution off the machine.

If either proof fails, the answer is to improve the local edge broker and its
governance contracts, not to add a shared runtime.

## Decision Gates

Before any shared runtime design starts, these decisions must have written
contracts and tests:

The required gates are tenant isolation, authorization, quotas, session
affinity, distributed state, cost controls, audit, and failure domains.
Contract statement: session affinity must be designed before shared runtime.

| Gate | Required decision |
|---|---|
| Tenant isolation | Define how workspaces, users, upstream state, tokens, logs, and runtime files are separated. |
| Authorization | Define who can publish bundles, approve rollout, call tools, view status, and perform rollback. |
| Quotas | Define per-user, per-team, per-upstream, and per-tool limits before any pooled runtime exists. |
| Session affinity | Define whether stateful upstreams stay bound to one session, one machine, one user, or one hosted worker. |
| Distributed state | Define storage, locking, rollback, recovery, and conflict behavior for deployment state outside one filesystem. |
| Cost controls | Define budget limits, rate limits, metering, owner attribution, and kill switches before shared execution. |
| Audit | Define immutable event records for config publication, approval, apply, rollback, tool calls, and policy denial. |
| Failure domains | Define blast radius, isolation boundaries, degraded mode, rollback mode, and break-glass behavior. |

No gate can be satisfied by prose alone. Each gate needs a testable contract,
a default-deny behavior, and a migration path from the local runtime.

## Mandatory Non-Goals

Phase 3 does not add hosted execution. It does not add remote tool calls, remote
upstream startup, central OAuth storage, central browser state, or shared
filesystem access. It does not make a future cloud service part of the default
install path.

The public repo must keep working for a single user who clones it, creates a
private config, and runs the broker locally.
