# Governance Bundles

Governance bundles are desired-state documents for `mcp-broker`. They describe
profiles, upstream catalog entries, client render targets, policy, provenance,
and compatibility metadata. They do not execute code and they do not change live
runtime state by themselves.

The current contract supports local validation from disk. Deployment behavior is
a separate follow-up step in the phase plan.

## Bundle Shape

The JSON Schema lives at `config/broker.bundle.schema.json`. A valid bundle has
these required sections:

- `schema_version`: bundle schema version. The current version is `1`.
- `bundle_id`: stable bundle identifier.
- `version`: bundle version string.
- `channel`: release or rollout channel.
- `source`: provenance for the bundle file or artifact.
- `checksum`: SHA-256 checksum metadata.
- `applies_to`: target broker identity and environment list.
- `profiles`: desired profile settings.
- `upstreams`: desired upstream catalog entries.
- `clients`: desired client render targets.
- `policy`: approval and execution policy.
- `compatibility`: supported config schema range and required features.

## Local Validation

Validate a bundle without changing runtime state:

```bash
mcp-broker bundle validate --bundle path/to/bundle.json
make bundle-validate BUNDLE=path/to/bundle.json
```

Validation checks:

- JSON object shape against `config/broker.bundle.schema.json`
- bundle schema version
- SHA-256 checksum
- config schema compatibility range
- local file existence

The checksum covers the canonical JSON bundle after replacing
`checksum.value` with 64 zero characters. This gives the bundle a stable
self-check without requiring external checksum sidecars.

## Execution Boundary

Bundles are data. The schema enforces:

- no unknown top-level sections
- `policy.approval_required` must be `true`
- `policy.allow_remote_code_execution` must be `false`
- `policy.mutating_upstreams_require_allowlist` must be `true`
- compatibility is rejected unless the current broker config schema version is
  inside the bundle's supported range

This keeps a published bundle from becoming an arbitrary installer. Later tasks
can validate, stage, apply, and roll back bundles, but those steps remain local
and approval-gated.

## Split Governance Documents

Phase 2 separates desired state into publishable documents:

- profile bundle: profile exposure, compact tools, tool budgets, and mutating
  allowlists
- upstream catalog bundle: approved upstream templates, lifecycle defaults,
  tags, purpose, and smoke-probe shape
- policy bundle: `approval_required`, `allow_remote_code_execution`,
  `mutating_upstreams_require_allowlist`, redaction, and break-glass rules
- rollout bundle: canary, staged rollout, health gates, approval points, and
  rollback triggers
- compatibility bundle: broker version, config schema range, required features,
  deprecations, and compatibility rejection reasons

These are publishable documents, not executable packages. They let a team govern
the local broker without turning the broker into a hosted service.

## Local Control-Plane Contract

Governance documents are evaluated by the local broker. The contract is:

- execution stays local
- local broker validation happens before stage or apply
- local simulation only until rollout behavior is proven
- no central service starts upstream MCP processes
- no central service calls tools on behalf of a user
- no inbound remote tool-call listener is introduced by these documents

See `docs/governance-control-plane.md` for the Phase 2 control-plane contract.

## Current Status

- P1.2 defines the desired-state schema and helper metadata.
- P1.3 adds local bundle validation from disk.
- P1.4 adds transactional deployment state and rollback records.
- P2.1 splits the bundle model into profile, upstream-catalog, policy, rollout,
  and compatibility documents for enterprise governance.
