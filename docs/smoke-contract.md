# Smoke Contract

This project is a local process broker. The smoke suite must prove the broker
can reach real configured MCP upstreams without mocks while keeping unsupported
domains explicit.

Required smoke coverage:

- health/readiness/live: `scripts/doctor.sh` creates the runtime root and required directories.
- auth/token: secrets and tokens live outside the repo under the configured runtime root.
- local-stdio: live tests discover enabled stdio upstreams from YAML and list tools through the broker.
- remote-http: live tests discover enabled HTTP upstreams from YAML and list tools through broker-managed streamable HTTP.
- configured-smoke: live tests execute each enabled upstream's configured safe smoke probe when one exists.
- protected-profile: live tests verify compact or protected profiles from YAML without naming a user's private upstreams.
- billing/tier/quota/entitlement: unsupported. The broker does not meter usage, own subscriptions, or define customer entitlements.
- profile/user: client profiles are policy config, not user accounts.
- voice/audio/speech: unsupported. The broker routes MCP JSON-RPC and does not capture audio.
- core/workflow: Makefile entrypoints and config loading are the current executable broker workflow.

Codex, Claude, Gemini, and other client configs stay untouched until a separate
wiring task applies the rendered broker shim config.
