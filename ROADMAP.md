# Roadmap

This roadmap is product-facing. Private agent task history and local upstream inventory stay out of the public repo.

## 0.1.0

- Local broker daemon over a Unix socket.
- Stdio client shim for MCP clients.
- Compact broker facade with search, describe, call, and status tools.
- YAML config contract with JSON Schema validation.
- Profile gates for Codex, Claude, Gemini, and manual test flows.
- macOS LaunchAgent, Linux systemd user service, and Windows Scheduled Task install flows.
- CLI-first package commands: `mcp-broker init`, `mcp-broker start`, `mcp-broker status`, and `mcp-broker render`.
- Public quality gates, release smoke, and context-reduction measurement.
- Private-To-Public Export pipeline for creating a clean public checkout from the private working repo.
- Public distribution, GitHub publication, and community launch checklists.

## Next

- PyPI package for `pipx install mcp-broker`.
- `uv tool install` documentation after package validation.
- Homebrew formula after the Python package path is stable.
- Official MCP Registry metadata and release automation.
- Docker or OCI mode only after host-bound state, mounts, and support boundaries are documented.
- Public comparison guide against MCP gateways, registries, and simple proxies.
- Adoption guide for users who run Codex, Claude, Cursor, or other MCP clients with too many always-loaded tools.
- Public safety docs for mutating tools, OAuth state, browser state, filesystem roots, database URLs, and profile allowlists.
- Transport policy docs for stdio, HTTP, streamable HTTP, SSE, and WebSocket compatibility boundaries.

## Public Export

The first public repo must come from the export pipeline, not by changing visibility on the private repo. The public checkout should contain only allowlisted source, tests, docs, config examples, and release files.

Before first public push:

- Run `make public-export-check PUBLIC_REPO=<clean-public-checkout>`.
- Review root docs, issue templates, screenshots or GIF, and release notes.
- Confirm no private docs, private inventory, runtime state, generated reports, or private git history are present.
- Run the public test gate from the exported checkout.
