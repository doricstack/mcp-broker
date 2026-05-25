# Upstream Compatibility Matrix

This matrix is derived from `config/broker.example.yaml`. Private upstream
inventories must stay in ignored local config and should not be committed here.

`Auth` records how the broker receives credentials. `environment` means an
environment variable name is configured, `secret files` means the broker reads a
runtime secret file, and `none` means the record has no credential source in
broker config.

`Mutation Risk` is conservative. Disabled examples keep `mutating` when enabling
that upstream later would grant write, deploy, filesystem, database,
browser-state, or OAuth-backed access.

| Upstream | Mode | Transport | Auth | Mutation Risk | Default Profile Exposure |
| --- | --- | --- | --- | --- | --- |
| `example-store` | `disabled` | `stdio` | none | read-only | manual-test |
| `example-python` | `per_session` | `stdio` | none | read-only | manual-test |
| `example-env-auth` | `disabled` | `stdio` | environment | read-only | manual-test |
| `example-file-auth` | `disabled` | `stdio` | secret files | read-only | manual-test |
| `example-request-meta-auth` | `disabled` | `stdio` | secret files | read-only | manual-test |
| `example-http` | `disabled` | `http` | environment | read-only | manual-test |
| `example-mutating` | `disabled` | `stdio` | none | mutating | protected |
