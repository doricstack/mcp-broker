# GitHub Publication

Use this page when creating the clean public GitHub repo. Do not change the
visibility of the private repo.

## Repository Metadata

Set the repository description exactly enough that GitHub search users see the
problem and target clients.

repository description:

```text
Local MCP broker that exposes one compact MCP entry for MCP clients while routing to many configured upstream servers.
```

Topics:

```text
mcp
model-context-protocol
mcp-client
codex
claude
gemini-cli
mcp-server
mcp-gateway
developer-tools
ai-tools
```

Website:

```text
https://github.com/<owner>/mcp-broker#readme
```

## Pinned Demo Issue

Create a pinned demo issue titled:

```text
Demo: reduce always-loaded MCP tools with one broker entry
```

Issue body:

```text
This issue tracks the first public demo.

The demo should show:
- starting from the public example config
- running `mcp-broker init`
- rendering one MCP client entry
- using `broker_search_tools`, `broker_describe_tool`, `broker_call_tool`, and `broker_status`
- comparing 609 to 43 advertised tool definitions and 276,989 to 45,281 serialized `o200k_base` tool tokens
```

## Current Release Notes

Release title:

```text
mcp-broker $(PACKAGE_VERSION)
```

Use these release notes as the starting body:

release notes:

```text
mcp-broker $(PACKAGE_VERSION) is the current stable public release.

Highlights:
- one compact MCP facade for many upstream MCP servers
- profile gates for MCP client profiles, including Codex, Claude, Gemini, and manual test flows
- YAML config with JSON Schema validation
- shared and per-session upstream process modes
- macOS LaunchAgent, Linux systemd user service, and Windows Scheduled Task install flows
- public export gate for clean-history release from a private working repo
- Linux release-gate parity for the PyPI workflow path
- measured context reduction: 609 to 43 advertised tool definitions and 276,989 to 45,281 serialized `o200k_base` tool tokens

Docs:
- README.md
- docs/install.md
- docs/context-reduction-measurement.md
- docs/safety.md
- docs/distribution.md
```

Before publishing the release, attach any generated artifacts only from the
clean public checkout. Do not attach private repo archives or private runtime
logs.
