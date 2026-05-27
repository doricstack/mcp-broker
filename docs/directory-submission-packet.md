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

Context-reduction evidence:

```text
https://github.com/NavinAgrawal/mcp-broker/blob/main/docs/context-reduction-measurement.md
```

Validation before submission:

```bash
make directory-submission-check
```

## Primary Directories

Submit in this order after the package works from a clean machine:

- Official MCP Registry: use `registry/server.json` and `mcp-publisher`.
- Glama: listed at `https://glama.ai/mcp/servers/NavinAgrawal/mcp-broker`.
  Verify rendered tool schemas, safety annotations, install docs, license, and
  score after each public metadata refresh. Use Glama's Server tab for future
  reindex or correction requests. Do not use the Connector tab unless a future
  release exposes a hosted HTTPS MCP URL.
- PulseMCP: listed at
  `https://www.pulsemcp.com/servers/navinagrawal-mcp-broker` through registry
  ingestion. Verify the rendered `server.json` name, provider, GitHub link, and
  description after each public metadata refresh. If the entry disappears,
  submit the public GitHub repository at `https://www.pulsemcp.com/submit`.
- Smithery: use the local stdio/MCPB path only after package install, config,
  upgrade, and uninstall smoke passes.
- Docker MCP Catalog: submit after Dockerfile and custom catalog smoke pass.

Smithery MCPB command after account or namespace auth is ready:

```bash
make mcpb-pack
smithery mcp publish dist/mcp-broker-1.1.0.mcpb -n <smithery-namespace>/mcp-broker
```

Smithery publishes the MCPB bundle as `server.mcpb`; keep the source manifest
at `mcpb/manifest.json` and rerun `make mcpb-smoke` before upload.

Claude Desktop local MCPB smoke uses the desktop extension path, not the remote
custom connector URL path:

```text
Settings -> Extensions -> Advanced settings -> Extension Developer -> Install Extension...
```

Install `dist/mcp-broker-1.1.0.mcpb`, confirm `mcp-broker` appears, confirm
`broker.search_tools`, `broker.describe_tool`, `broker.call_tool`, and
`broker.status`, run one safe status or search call, reinstall once, then
uninstall.

## Secondary Directories

Use the same packet for:

- `mcpservers.org`
- `mcp.so`
- `MCPCentral`
- Active awesome-MCP-server lists that accept pull requests

Current submission requirements checked on 2026-05-27:

- mcpservers.org requires a contact email on `https://mcpservers.org/submit`.
- mcp.so requires Sign In before accepting `https://mcp.so/submit`. Use this
  server config, not the page's generic GitHub Docker placeholder:

```json
{
  "mcpServers": {
    "mcp-broker": {
      "command": "uvx",
      "args": ["mcp-broker", "stdio", "--init-if-missing"],
      "env": {}
    }
  }
}
```

- MCPCentral requires the publisher flow:
  `mcp-publisher login github --registry https://registry.mcpcentral.io`, then
  `mcp-publisher publish`.
- `wong2/awesome-mcp-servers` points new submissions to
  `https://mcpservers.org/submit`, so do not open a duplicate PR there unless
  the maintainer guidance changes.

Before submitting each one, verify the listing shows:

- `broker.search_tools`
- `broker.describe_tool`
- `broker.call_tool`
- `broker.status`
- install command
- config location
- safety notes
- context-reduction evidence link
