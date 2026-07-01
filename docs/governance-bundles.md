# Governance Bundles

Governance bundles are desired-state documents for `mcp-broker`. They describe
profiles, upstream catalog entries, client render targets, policy, provenance,
and compatibility metadata. They do not execute code and they do not change live
runtime state by themselves.

The current contract is schema-only. Validation and deployment behavior are
separate follow-up steps in the phase plan.

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

## Execution Boundary

Bundles are data. The schema enforces:

- no unknown top-level sections
- `policy.approval_required` must be `true`
- `policy.allow_remote_code_execution` must be `false`
- `policy.mutating_upstreams_require_allowlist` must be `true`
- compatibility is pinned to config schema version `1`

This keeps a published bundle from becoming an arbitrary installer. Later tasks
can validate, stage, apply, and roll back bundles, but those steps remain local
and approval-gated.

## Current Status

- P1.2 defines the desired-state schema and helper metadata.
- P1.3 will add local bundle validation from disk.
- P1.4 will add transactional deployment state and rollback records.
- P2 will split the bundle model into profile, upstream-catalog, policy,
  rollout, and compatibility documents for enterprise governance.
