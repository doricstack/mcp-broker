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
${GITHUB_REPOSITORY_URL}
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
${GITHUB_REPOSITORY_URL}/blob/main/docs/context-reduction-measurement.md
```

Validation before submission:

```bash
make directory-submission-check
```

## Primary Directories

Submit in this order after the package works from a clean machine:

- Official MCP Registry: use `registry/server.json` and `mcp-publisher`.
- Glama: listed at `${GLAMA_LISTING_URL}`.
  Verify rendered tool schemas, safety annotations, install docs, license, and
  score after each public metadata refresh. Use Glama's Server tab for future
  reindex or correction requests. Do not use the Connector tab unless a future
  release exposes a hosted HTTPS MCP URL. Root `glama.json` declares
  `${GLAMA_MAINTAINER}` as the maintainer for Glama claim metadata.
- PulseMCP: listed at
  `${PULSEMCP_LISTING_URL}` through registry
  ingestion. Verify the rendered `server.json` name, provider, GitHub link, and
  description after each public metadata refresh. If the entry disappears,
  submit the public GitHub repository at `${PULSEMCP_SUBMIT_URL}`.
- Smithery: published via the local stdio/MCPB path. Release
  `${SMITHERY_RELEASE_ID}` returned `SUCCESS`; MCP URL:
  `${SMITHERY_MCP_URL}`.
- Docker MCP Catalog: submit after Dockerfile and custom catalog smoke pass.

Smithery MCPB command after account or namespace auth is ready:

```bash
make smithery-payload-check
smithery auth login
smithery namespace use ${SMITHERY_NAMESPACE}
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
  "args": ["mcp-broker", "stdio", "--profile", "${user_config.profile}", "--init-if-missing"]
}
```

Claude Desktop local MCPB smoke uses the desktop extension path, not the remote
custom connector URL path:

```text
Settings -> Extensions -> Advanced settings -> Extension Developer -> Install Extension...
```

Install `dist/mcp-broker-${PACKAGE_VERSION}.mcpb`, confirm `mcp-broker` appears, confirm
`broker_search_tools`, `broker_describe_tool`, `broker_call_tool`, and
`broker_status`, run one safe status or search call, reinstall or replace the
bundle once if Claude Desktop offers that action, then uninstall. The current
Claude Desktop extension UI may not expose a separate upgrade action; reinstall
or replace is the available upgrade-equivalent path for this local MCPB.

Anthropic publication closeout checked on 2026-05-30: this package does not
have a hosted HTTPS MCP endpoint, so Claude's remote Custom Connector form is
not the right submission path. The local MCPB path is Claude Desktop
Extensions. Anthropic's third-party desktop extension interest form requires a
signed-in browser session and returns `401 Unauthorized` to non-browser
automation, so keep the repo-owned deliverable as the validated MCPB bundle and
submit through a maintainer browser session only if Anthropic opens that path
for local extensions.

## Secondary Directories

Use the same packet for:

- `MCPSERVERS`
- `MCP_SO`
- `MCPCentral`
- Active awesome-MCP-server lists that accept pull requests

Current submission requirements checked on 2026-05-30:

- MCPSERVERS: approved at
  `${MCPSERVERS_LISTING_URL}`.
- MCP_SO: live at `${MCP_SO_LISTING_URL}`.
  Verified on 2026-05-28 with HTTP 200 and page content containing
  `mcp-broker`, `${GLAMA_MAINTAINER}`, and the public GitHub repository. Use this
  server config for any future refresh, not the page's generic GitHub Docker
  placeholder. If the MCP_SO Tools tab returns `get server tools failed:no
  tools found`, the listing is missing `--profile docker`; the public example
  config is profile-gated and the compact broker tools are exposed through the
  Docker/public listing profile:

```json
{
  "mcpServers": {
    "mcp-broker": {
      "command": "uvx",
      "args": ["mcp-broker", "stdio", "--profile", "docker", "--init-if-missing"],
      "env": {}
    }
  }
}
```

- MCPCentral requires the publisher flow:
  `mcp-publisher login github --registry ${MCPCENTRAL_REGISTRY_URL}`, then
  `mcp-publisher publish`. As of 2026-05-30,
  `${MCPCENTRAL_REGISTRY_URL}` currently does not resolve, so publishing is blocked
  before GitHub OAuth can start. The browser submit page at
  `${MCPCENTRAL_SUBMIT_URL}` redirects to sign-in and Cloudflare
  blocks non-browser automation. No repo-owned publication path remains until
  the registry host resolves or a signed-in maintainer browser session exposes
  a working publish path.
- `wong2/awesome-mcp-servers` points new submissions to
  `${MCPSERVERS_SUBMIT_URL}`, so do not open a duplicate PR there unless
  the maintainer guidance changes.
- `punkpeye/awesome-mcp-servers` PR:
  `${PUNKPEYE_AWESOME_PR_URL}`.
- `appcypher/awesome-mcp-servers` PR creation is unavailable. The repo API is
  readable, but the pulls API returns `404 Not Found`, and the browser compare
  page reports that the owner disabled pull requests. The fork branch exists at
  `${APPCYPHER_AWESOME_FORK_BRANCH_URL}`.
  If that repository reopens submissions later, use the compare URL:
  `${APPCYPHER_AWESOME_COMPARE_URL}`.

Before submitting each one, verify the listing shows:

- `broker_search_tools`
- `broker_describe_tool`
- `broker_call_tool`
- `broker_status`
- install command
- config location
- safety notes
- context-reduction evidence link
