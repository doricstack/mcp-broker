# Distribution

This page tracks public distribution paths for `mcp-broker`.

## Python Package

Package metadata is release-aligned for `1.0.0`. The version is sourced from
`src/mcp_broker/__init__.py`; `pyproject.toml` reads that value through
Setuptools dynamic metadata.

Current public package status:

- PyPI: `mcp-broker 1.0.0` is published.
- MCP Registry: `io.github.NavinAgrawal/mcp-broker 1.0.0` is published and marked latest.
- Homebrew: `mcp-broker 1.0.0` is published through the public tap.

The package command surface is:

```bash
mcp-broker init
mcp-broker stdio
mcp-broker start
mcp-broker status
mcp-broker render codex --dry-run
```

The install command is:

```bash
pipx install mcp-broker
```

`pyproject.toml` exposes `mcp-broker`, `mcp-broker-client`, and
`mcp-broker-daemon`. It also packages `config/broker.example.yaml` as shared
package data so `mcp-broker init` can create a private config outside a source
checkout.

`uv` uses the same package:

```bash
uv tool install mcp-broker
uvx mcp-broker status
```

Repository-owned package checks:

```bash
make package-check
```

Publishing is automated by `.github/workflows/publish-pypi.yml`. The workflow
runs `make release-gate` before the PyPI publish step. It runs for published
GitHub releases, manual dispatches, and the `publish-pypi` repository-dispatch
event. Tag pushes do not publish to PyPI; the GitHub Release publication is the
single normal release event. The publish step uses `skip-existing: true` as a
secondary guard against manual reruns for the same package files.

`.github/workflows/publish-python.yml` is a workflow-ID recovery fallback for
cases where GitHub Actions stops dispatching the primary workflow record. PyPI
Trusted Publishing must trust the fallback workflow filename before it can
publish with OIDC.

Before tagging a release, run:

```bash
make release-gate
```

That target keeps mutation last and writes mutation evidence under
`var/quality/mutation_stats.json`.

Before publishing from GitHub Actions, run the Linux parity gate when Docker is
available:

```bash
make linux-release-gate
```

That target runs the PyPI workflow release gate inside a Linux container with
`GITHUB_ACTIONS`, `RUNNER_TEMP`, `HOME`, and `XDG_CONFIG_HOME` set to runner-like
values.

## Homebrew

Homebrew is published through:

```bash
brew tap NavinAgrawal/tap
brew install mcp-broker
```

The formula installs the same console scripts, leaves user client configs
untouched during install, and preserves the runtime root contract:

```text
$HOME/mcp/mcp-broker/
```

The public tap points to the PyPI `1.0.0` source artifact. Retest the formula
against the PyPI source artifact before changing the Homebrew release status.

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

`1.0.0` is published after PyPI publication and the registry marks `1.0.0` as
the latest entry.

Reference docs:

- https://modelcontextprotocol.io/registry/about
- https://modelcontextprotocol.io/registry/authentication
- https://modelcontextprotocol.io/registry/package-types
- https://modelcontextprotocol.io/registry/quickstart
- https://modelcontextprotocol.io/registry/versioning

## Docker And OCI

Docker mode is not the default local desktop experience. It is useful for
container-friendly upstreams and remote transports. The Docker image does not
edit host client files by default.

Build and smoke locally:

```bash
make docker-smoke
```

Build a release image with OCI labels, SBOM, and provenance:

```bash
make docker-buildx \
  DOCKER_IMAGE=ghcr.io/<owner>/mcp-broker:1.0.0 \
  DOCKER_PLATFORMS=linux/amd64,linux/arm64 \
  DOCKER_PUSH=1
```

For a local one-platform buildx check without pushing:

```bash
make docker-buildx DOCKER_PLATFORMS=linux/arm64
```

Run manually:

```bash
docker build -t mcp-broker:local .
docker run --rm -i mcp-broker:local
```

The image entrypoint calls the package-owned stdio lifecycle:

```bash
mcp-broker stdio --init-if-missing
```

Boundary:

- Supported: HTTP, streamable HTTP, SSE, and stdio upstreams that run inside
  the container.
- Supported: explicit mounts for runtime state, config, logs, and secrets.
- Unsupported by default: hidden edits to host `~/.codex`, `~/.claude.json`, or
  browser profiles.
- Required before Docker MCP Catalog PR approval: Docker MCP Toolkit custom
  catalog smoke, public image publication, and a Docker-specific security
  review.

Docker MCP Catalog submission uses the Docker registry PR flow after the
public repo contains the Dockerfile.

## MCPB, Smithery, Glama, PulseMCP, And Directories

Use the clean public GitHub repo as the source for indexers. Submit after the
README, safety docs, package install path, and registry metadata are stable.

MCPB metadata lives in:

```text
mcpb/manifest.json
```

Validate it with:

```bash
make mcpb-validate
```

Smithery has two possible paths:

- Hosted or remote mode: publish a streamable HTTP URL.
- Local mode: publish an MCPB bundle from `mcpb/manifest.json` only if install,
  config, upgrade, and uninstall behavior are visible to the user.

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
