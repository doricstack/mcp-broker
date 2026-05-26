# Directory Submission Packet

Use this copy after the public release, PyPI package, and registry metadata are
live. Do not submit a directory listing from the private checkout.

## Project

Name: `mcp-broker`

Short description:

```text
Local MCP broker that exposes one compact MCP entry while routing to many configured upstream servers.
```

Repository:

```text
https://github.com/NavinAgrawal/mcp-broker
```

Install:

```bash
pipx install mcp-broker
mcp-broker init
mcp-broker render codex --dry-run
```

Categories:

```text
developer-tools
mcp
local-infrastructure
ai-tools
```

Safety notes:

```text
Runtime state stays outside the repository. Local upstreams are configured in user-owned YAML. Mutating tools require profile allowlists. Secrets should be referenced by environment variable name or runtime secret file, not committed to config.
```

## Primary Directories

Submit in this order after the package works from a clean machine:

- Official MCP Registry: use `registry/server.json` and `mcp-publisher`.
- Glama: submit the public GitHub repository and verify rendered tool schemas.
- PulseMCP: submit the public GitHub repository or rely on official registry ingestion when available.
- Smithery: use the local stdio/MCPB path only after package install, config,
  upgrade, and uninstall smoke passes.
- Docker MCP Catalog: submit after Dockerfile and custom catalog smoke pass.

## Secondary Directories

Use the same packet for:

- `mcpservers.org`
- `mcp.so`
- `MCPCentral`
- Active awesome-MCP-server lists that accept pull requests

Before submitting each one, verify the listing shows:

- `broker.search_tools`
- `broker.describe_tool`
- `broker.call_tool`
- `broker.status`
- install command
- config location
- safety notes
- context-reduction evidence link
