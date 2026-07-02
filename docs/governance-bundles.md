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

## Layered Config Composition

Large teams can compose an effective broker config from layered documents before
anything is applied to runtime state. The merge order is fixed:

```text
org -> team -> add-on -> user
```

Maps merge recursively. Lists and scalar values are replaced by the later layer.
The composer reports:

- `effective_config`: the merged config document
- `effective_config_digest`: a SHA-256 digest of canonical JSON
- `layers`: the layer names in merge order
- `provenance`: the final source layer and file for each leaf path
- `conflicts`: paths where a later layer replaced an earlier value
- `changed_runtime_state: false`

Dry-run composition:

```bash
mcp-broker config compose \
  --org org.yaml \
  --team team.yaml \
  --addon audit.yaml \
  --user user.yaml
```

Layer documents may name secrets, but they must not contain secret values. Use
`secret_ref` with an environment-variable name:

```yaml
upstreams:
  github:
    env:
      GITHUB_TOKEN:
        secret_ref: GITHUB_TOKEN
```

Literal values under token, secret, credential, password, API key, or key fields
are rejected before a digest is produced.

## Local Control-Plane Contract

Governance documents are evaluated by the local broker. The contract is:

- execution stays local
- local broker validation happens before stage or apply
- local simulation only until rollout behavior is proven
- no central service starts upstream MCP processes
- no central service calls tools on behalf of a user
- no inbound remote tool-call listener is introduced by these documents

See `docs/governance-control-plane.md` for the Phase 2 control-plane contract.

## Signed Publishing Metadata

Governance bundles may include a `publish` section when they are prepared for a
channel. The section records `signature_ref`, `promotion_state`, `revoked`, and
source `provenance`. Local publishing rejects candidates without a signature
reference, rejects bundles whose checksum does not verify, and refuses revoked
candidates before promotion metadata is written.

## Break-Glass Audit

Break-glass is a local, time-bound policy bypass record. It is for emergency
operator action only, and it must leave an audit record before any bypassed
policy path is treated as active.

Create a record with an operator, reason, expiration, and one or more bypassed
policy paths:

```bash
make break-glass-create \
  BREAK_GLASS_OPERATOR=operator@example.com \
  BREAK_GLASS_REASON="Emergency runtime recovery" \
  BREAK_GLASS_EXPIRES_AT=2099-07-01T12:30:00Z \
  BREAK_GLASS_BYPASS_POLICY_PATHS="policy.rollout.approval policy.bootstrap.apply"
```

Inspect status:

```bash
make break-glass-status
mcp-broker break-glass status --state-dir ~/mcp/mcp-broker/state
```

Records live under `state/break-glass/`. The active pointer is
`state/break-glass/active.json`, record files live under
`state/break-glass/records/`, and the append-only audit log is
`state/break-glass/audit.jsonl`.

While a valid record is active, daemon status reports `status: degraded` and
adds a `break_glass` object with `degraded: true`, the active record, expiration,
operator, reason, and bypassed policy paths. Expired records are rejected for
active use and status returns inactive.

## Current Status

- P1.2 defines the desired-state schema and helper metadata.
- P1.3 adds local bundle validation from disk.
- P1.4 adds transactional deployment state and rollback records.
- P1.N5 adds dry-run layered config composition with digest, provenance,
  conflict reporting, and secret-reference validation.
- P1.N6 adds local break-glass audit records with reason, operator, expiration,
  bypassed policy paths, and degraded status.
- B2.1 splits the bundle model into profile, upstream-catalog, policy, rollout,
  and compatibility documents for enterprise governance.
- P2.1 adds signed publishing metadata and local publish manifests.
