# Codex Deferred Tool Acceptance

This check is maintainer-only because it must run from an active Codex session
where the deferred MCP wrapper tools are present. It must not be part of
`make quality-gate`.

Generate the acceptance steps from the configured YAML:

```bash
make codex-deferred-acceptance
```

Use JSON output when pasting into an audit record:

```bash
make codex-deferred-acceptance DEFERRED_ACCEPTANCE_FORMAT=json
```

The generator reads every enabled upstream visible to the selected profile and
uses the upstream `smoke` block. For each upstream it prints the exact Codex
wrapper calls:

- `mcp__mcp_broker__.broker_search_tools`
- `mcp__mcp_broker__.broker_describe_tool`
- `mcp__mcp_broker__.broker_call_tool`

The generated call sequence is:

1. Search for the configured safe probe query.
2. Describe the configured safe probe tool.
3. Call the configured safe probe tool, unless `smoke.call` is `false`.

The script fails if any enabled profile-visible upstream lacks a `smoke` probe.
That keeps the acceptance list dynamic and prevents a stale hand-written MCP
inventory.

Run this only after broker-owned checks pass:

```bash
make codex-profile-validation
make codex-claude-discovery-parity
make codex-deferred-acceptance
```

Acceptance passes when every generated search and describe call succeeds, every
generated safe call succeeds, and `/mcp` shows only the intended local entries.
Claude wiring uses the same profile-owned checks and requires explicit approval
before applying Claude config rendering.
