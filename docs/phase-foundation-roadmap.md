# Phase Foundation Roadmap

This roadmap describes the public product sequence for plugin setup, enterprise
governance, and shared-runtime guardrails. Private local upstream inventory,
operator notes, and maintainer task history stay out of this document.

## Current Position

`mcp-broker` is a local edge broker. It runs on the engineer's machine, reads
local YAML config, exposes one compact MCP server to clients, and routes calls to
configured upstream MCP servers. That remains the default execution boundary.

The next work adds contracts around that local runtime so the same repo can serve
individual users, small teams, and larger enterprises without requiring a hosted
control plane on day one.

## Phase 1: Plugin And Local Deployment Foundation

- [x] Add a config-backed broker identity/status contract with `broker_id`,
      `environment`, `bundle_version`, `schema_version`, active profile, and
      configured profile set.
- [x] Define a desired-state bundle schema for profiles, upstream catalog
      entries, client render targets, policy, compatibility, and provenance.
- [ ] Add a local bundle validator and loader that rejects invalid schema,
      version, checksum, and compatibility input without changing runtime state.
- [ ] Add transactional deployment state under the runtime state directory,
      including active and previous pointers, rollback journal, and recovery from
      partial writes.
- [ ] Add a plugin package contract with repo-owned install, status, dry-run,
      apply, rollback, and smoke checks.
- [ ] Make the public clone-to-running path work through `make setup`, config
      initialization, profile validation, smoke checks, client render, rollback,
      and troubleshooting.

## Phase 2: Governance Contracts

- [ ] Split desired state into publishable profile, upstream-catalog, policy,
      rollout, and compatibility bundle documents.
- [ ] Add a redacted fleet-status export that reports broker identity, bundle
      version, health, counters, and upstream state without local paths, account
      names, secret values, or private inventory.
- [ ] Add an offline control-plane simulator for canary, staged rollout,
      rollback, compatibility rejection, and approval decisions.

## Phase 3: Shared-Runtime Guardrails

- [ ] Document that shared hosted execution is not implemented.
- [ ] Require Phase 1 value proof and Phase 2 governance proof before designing a
      shared execution runtime.
- [ ] Define the decision gates for tenant isolation, authorization, quotas,
      session affinity, distributed state, cost controls, audit, and failure
      domains.

## Non-Goals

- Do not move default execution away from the local machine.
- Do not add a remote listener without enforcing `broker.remote_auth` before
  request handling.
- Do not publish local private upstream inventory, account names, filesystem
  paths, or runtime state.
- Do not build shared hosted execution until the plugin and governance contracts
  are proven in local workflows.
