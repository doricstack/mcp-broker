# Distribution

This page tracks public distribution paths for `mcp-broker`. The source
checkout flow remains the reference path until the clean public repo, release
tag, and package upload exist.

## Python Package

Package metadata is release-aligned at `0.1.1`. The version is sourced from
`src/mcp_broker/__init__.py`; `pyproject.toml` reads that value through
Setuptools dynamic metadata.

The package command surface is:

```bash
mcp-broker init
mcp-broker start
mcp-broker status
mcp-broker render codex --dry-run
```

The planned install command is:

```bash
pipx install mcp-broker
```

`pyproject.toml` exposes `mcp-broker`, `mcp-broker-client`, and
`mcp-broker-daemon`. It also packages `config/broker.example.yaml` as shared
package data so `mcp-broker init` can create a private config outside a source
checkout.

`uv` should use the same package once the PyPI release exists:

```bash
uv tool install mcp-broker
uvx mcp-broker status
```

Repository-owned package checks:

```bash
make package-check
```

Publishing is automated by `.github/workflows/publish-pypi.yml`, but the first
upload still requires a PyPI project or Trusted Publisher setup for the public
GitHub repository.

## Homebrew

Homebrew should come after the PyPI package path is validated. The formula or
tap must install the same console scripts, leave user client configs untouched
during install, and preserve the runtime root contract:

```text
$HOME/mcp/mcp-broker/
```

## MCP Registry

The official MCP Registry uses `server.json` metadata and `mcp-publisher`.
The registry is in preview, so validate against the current schema before
publishing. This repo has two metadata files:

```text
registry/server.json
registry/server.template.json
```

The official metadata points to the PyPI package path. The template stays
generic for downstream forks.

Before publishing from GitHub Actions:

- Publish the `mcp-broker` package to PyPI.
- Confirm the PyPI package README contains `mcp-name: io.github.NavinAgrawal/mcp-broker`.
- Confirm `registry/server.json` and the PyPI package version match.
- Confirm the public GitHub repo has OIDC access to the MCP Registry namespace.
- Run `.github/workflows/publish-mcp-registry.yml`.

GitHub OIDC is the preferred auth path. The workflow runs:

```bash
mcp-publisher login github-oidc
cp registry/server.json server.json
mcp-publisher publish
```

PyPI package must exist first. The MCP Registry validates that the public
package matches the server metadata before accepting the entry.

Reference docs:

- https://modelcontextprotocol.io/registry/about
- https://modelcontextprotocol.io/registry/authentication
- https://modelcontextprotocol.io/registry/package-types
- https://modelcontextprotocol.io/registry/quickstart
- https://modelcontextprotocol.io/registry/versioning

## Docker And OCI

Docker mode is not the default local experience. It is useful only for
container-friendly upstreams and remote transports. A Docker image must not
edit host client files by default.

Docker support needs an explicit boundary:

- Supported: HTTP, streamable HTTP, SSE, and stdio upstreams that run inside
  the container.
- Supported: explicit mounts for runtime state, config, logs, and secrets.
- Unsupported by default: hidden edits to host `~/.codex`, `~/.claude.json`, or
  browser profiles.
- Required before publication: Docker MCP Toolkit custom catalog smoke, image
  labels, SBOM/provenance path, and a Docker-specific security review.

Docker MCP Toolkit migration guidance belongs here after that boundary is
implemented.

## Smithery, Glama, PulseMCP, And Directories

Use the clean public GitHub repo as the source for indexers. Submit after the
README, safety docs, package install path, and registry metadata are stable.

Smithery has two possible paths:

- Hosted or remote mode: publish a streamable HTTP URL.
- Local mode: publish an MCPB bundle only if install, config, upgrade, and
  uninstall behavior are visible to the user.

Glama and PulseMCP should index the public repo after the first release. Check
that tool names, schemas, install instructions, safety notes, and score output
render correctly before adding secondary directories.

Directory copy lives in:

```text
docs/directory-submission-packet.md
```

The public launch page lives in:

```text
docs/launch.md
```
