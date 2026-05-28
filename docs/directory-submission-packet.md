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
  release exposes a hosted HTTPS MCP URL. Root `glama.json` declares
  `NavinAgrawal` as the maintainer for Glama claim metadata.
- PulseMCP: listed at
  `https://www.pulsemcp.com/servers/navinagrawal-mcp-broker` through registry
  ingestion. Verify the rendered `server.json` name, provider, GitHub link, and
  description after each public metadata refresh. If the entry disappears,
  submit the public GitHub repository at `https://www.pulsemcp.com/submit`.
- Smithery: published via the local stdio/MCPB path. Release
  `aae18669-9500-4a5d-9870-8f9b3bfd404d` returned `SUCCESS`; MCP URL:
  `https://mcp-broker--navinagrawal.run.tools`.
- Docker MCP Catalog: submit after Dockerfile and custom catalog smoke pass.

Smithery MCPB command after account or namespace auth is ready:

```bash
make smithery-payload-check
smithery auth login
smithery namespace use navinagrawal
make smithery-publish
```

Smithery publishes the MCPB bundle as `server.mcpb`; keep the source manifest
at `mcpb/manifest.json` and rerun `make mcpb-smoke` before upload. The MCPB
manifest declares a `binary` runtime for Smithery compatibility and exposes
`UVX command path` so Claude Desktop users can provide an absolute `uvx` path
when the GUI environment cannot find `uvx`. The MCPB schema allows rich tool
descriptions but does not allow `inputSchema` under `tools`; keep schemas out
of `mcpb/manifest.json`. `make smithery-publish` uses the repo adapter because
The Smithery CLI version used for validation converts valid MCPB tool entries into a server card without
`inputSchema`, which the Smithery API rejects. The adapter lives at
`scripts/smithery_release.py` and injects the source-backed broker facade
schemas into the Smithery server-card payload.
The local stdio startup smoke helper lives at `scripts/mcpb_stdio_smoke.py`.

Before a Claude Desktop or Smithery update, run:

```bash
make mcpb-smoke
make mcpb-stdio-smoke
make smithery-payload-check
```

MCPB runtime command:

```json
{
  "command": "${user_config.uvx_path}",
  "args": ["mcp-broker", "stdio", "--init-if-missing"]
}
```

Claude Desktop local MCPB smoke uses the desktop extension path, not the remote
custom connector URL path:

```text
Settings -> Extensions -> Advanced settings -> Extension Developer -> Install Extension...
```

Install `dist/mcp-broker-$(PACKAGE_VERSION).mcpb`, confirm `mcp-broker` appears, confirm
`broker_search_tools`, `broker_describe_tool`, `broker_call_tool`, and
`broker_status`, run one safe status or search call, reinstall once, then
uninstall.

## Secondary Directories

Use the same packet for:

- `mcpservers.org`
- `mcp.so`
- `MCPCentral`
- Active awesome-MCP-server lists that accept pull requests

Current submission requirements checked on 2026-05-27:

- mcpservers.org: approved at
  `https://mcpservers.org/servers/navinagrawal/mcp-broker`.
- mcp.so: submitted on 2026-05-27. It requires Sign In before accepting
  `https://mcp.so/submit`; public listing URL is pending directory review. Use
  this server config, not the page's generic GitHub Docker placeholder:

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
  `mcp-publisher publish`. As of 2026-05-27,
  `registry.mcpcentral.io` currently does not resolve, so publishing is blocked
  before GitHub OAuth can start. The browser submit page at
  `https://mcpcentral.io/submit-server` redirects to sign-in and Cloudflare
  blocks non-browser automation, so complete this only after the registry host
  resolves or a signed-in maintainer browser session exposes a working publish
  path.
- `wong2/awesome-mcp-servers` points new submissions to
  `https://mcpservers.org/submit`, so do not open a duplicate PR there unless
  the maintainer guidance changes.
- `punkpeye/awesome-mcp-servers` PR:
  `https://github.com/punkpeye/awesome-mcp-servers/pull/6993`.
- `appcypher/awesome-mcp-servers` PR creation is blocked by GitHub
  `CreatePullRequest` permissions even though the fork branch exists at
  `https://github.com/NavinAgrawal/awesome-mcp-servers-1/tree/add-mcp-broker`.
  If the browser UI allows it, try the compare URL:
  `https://github.com/appcypher/awesome-mcp-servers/compare/main...NavinAgrawal:awesome-mcp-servers-1:add-mcp-broker`.

Before submitting each one, verify the listing shows:

- `broker_search_tools`
- `broker_describe_tool`
- `broker_call_tool`
- `broker_status`
- install command
- config location
- safety notes
- context-reduction evidence link
