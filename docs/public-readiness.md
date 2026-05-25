# Public Readiness

`mcp-broker` starts private.

Public release only makes sense if:
- Config examples are generic.
- Config edits are validated by `config/broker.schema.json` and the runtime loader through `make config-validate`.
- Private upstream inventory lives in `config/broker.private.yaml`, not the public example.
- Personal paths are absent from source.
- Auth storage is documented and safe.
- Upstream compatibility is documented from the private config without leaking private paths.
- Troubleshooting covers broker-owned cleanup, socket conflicts, broken upstream commands, auth failures, and profile denials.
- Release checklist requires quality gate, broker smoke, config dry run, rollback test, and no stale broker-owned resources.
- The broker works with more than one MCP client.
- Tests cover line-framed and header-framed MCP transports.
- Runtime install works without maintainer-specific shell wrappers.
- Root docs exist: `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, and `ROADMAP.md`.
- Issue templates exist for bug reports, config help, and upstream compatibility.
- GitHub topics are set before the first release: `mcp, model-context-protocol, codex, claude, mcp-server, mcp-gateway, developer-tools, ai-tools`.
- Package command docs cover `mcp-broker init`, `mcp-broker start`, `mcp-broker status`, and `mcp-broker render`.
- Distribution docs cover PyPI, `uv`, Homebrew, MCP Registry, Docker MCP Toolkit, Smithery, Glama, PulseMCP, and secondary directory timing.
- `make public-export-check PUBLIC_REPO=<clean-public-checkout>` passes before any public push.
- `make public-release-dry-run` passes from a clean exported public checkout before the first public push.
- The context-reduction measurement links to `docs/context-reduction-measurement.md`.

Until then, treat this as local infrastructure.
