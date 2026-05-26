# Comparison

Last checked: 2026-05-25.

`mcp-broker` is a local desktop broker for developers who run many MCP servers across MCP clients such as Codex, Claude, Gemini, Cursor, and similar tools. It is not trying to be a hosted gateway, registry, container runtime, or enterprise policy plane.

## Quick Matrix

| Option | Best Fit | Where `mcp-broker` Differs |
|---|---|---|
| Raw MCP client config | A few local tools in one client. | `mcp-broker` removes repeated client config, owns upstream process cleanup, and exposes a compact broker facade. |
| Simple MCP proxies | Forwarding one MCP server through one endpoint. | `mcp-broker` adds profile budgets, upstream namespaces, lifecycle policy, smoke probes, status, and rollback-oriented client rendering. |
| Docker MCP Gateway | Containerized MCP servers from Docker profiles and catalogs. | `mcp-broker` keeps host-local stdio and HTTP upstreams first-class and does not require container packaging. Docker is the better fit when container isolation and catalog packaging are required. |
| IBM ContextForge | Gateway, registry, proxy, API virtualization, observability, and multi-protocol federation. | `mcp-broker` is smaller local infrastructure for desktop agents. ContextForge is broader infrastructure for MCP, A2A, REST, and gRPC gateway use. |
| Microsoft MCP Gateway options | Azure or Microsoft-hosted governance for agents and MCP traffic. | `mcp-broker` is local and file-configured. Microsoft options are a better fit when the MCP estate belongs in Azure governance. |
| Smithery | MCP marketplace, registry, managed connections, OAuth handling, and distribution. | `mcp-broker` does not host or publish upstream MCPs. It can broker local use of servers found elsewhere. |
| Glama Gateway | MCP registry, inspector, hosted connectors, gateway, auth, logs, access control, and analytics. | `mcp-broker` keeps the control point on the developer machine and focuses on local client context reduction. Glama is better for hosted connector discovery, hosted execution, and managed gateway use. |

## When To Choose `mcp-broker`

Use it when the pain is local session overhead, and simple MCP proxies do not cover the process and profile controls you need:

- Codex, Claude, Gemini, Cursor, or another MCP client loads too many tools at startup.
- The same upstream MCP inventory is copied across multiple client config files.
- Local upstream processes remain after sessions end.
- You need one place for runtime state, secrets, logs, sockets, and rendered config backups.
- You want per-client profiles without rewriting every upstream entry per client.

## When To Choose Something Else

Docker MCP Gateway is a better first option when you want MCP servers packaged and run as containers with Docker-managed catalogs, profiles, secrets, and container limits.

ContextForge is a better fit when you need a broader gateway with API virtualization, federation, auth, observability, plugins, and production service deployment.

Microsoft-hosted gateway options are a better fit when governance belongs in Azure or Microsoft Foundry rather than on a developer machine.

Smithery and Glama are better fits for discovery, distribution, hosted connector access, and marketplace presence. `mcp-broker` can sit under those choices for local client control, but it is not a registry.

## Sources

- Docker MCP Gateway docs: https://docs.docker.com/ai/mcp-gateway/
- Docker MCP Catalog and Toolkit docs: https://docs.docker.com/ai/mcp-catalog-and-toolkit/
- IBM ContextForge repository: https://github.com/IBM/mcp-context-forge
- Microsoft Foundry MCP governance docs: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/governance
- Microsoft Azure API Management MCP overview: https://learn.microsoft.com/en-us/azure/api-management/mcp-server-overview
- Smithery documentation: https://smithery.ai/docs
- Glama MCP registry and gateway: https://glama.ai/
