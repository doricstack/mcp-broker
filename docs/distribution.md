# Distribution

This page tracks public distribution paths for `mcp-broker`.

## Python Package

Package metadata is release-aligned for `1.1.1`. The version is sourced from
`src/mcp_broker/__init__.py`; `pyproject.toml` reads that value through
Setuptools dynamic metadata.

Current public package status:

- PyPI: `mcp-broker 1.1.1` is published.
- MCP Registry: `io.github.NavinAgrawal/mcp-broker 1.1.1` is published and marked latest.
- Homebrew: `mcp-broker 1.1.1` is published through the public tap.
- NPM: `@navinagrawal/mcp-broker 1.1.1` is published.
- Docker: `docker.io/navinagrawal/mcp-broker:1.1.1` and
  `ghcr.io/navinagrawal/mcp-broker:1.1.1` are published.
- Current source release: `1.1.1`.

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

The public artifact gate downloads into a temporary directory and verifies the
same package surfaces a user receives:

```bash
make public-stable-surface-smoke
```

That stable gate verifies PyPI, `pipx`, `uvx`, GitHub release source archive,
Homebrew, and MCP Registry for the currently published stable version.

After each distribution release, the full release surface gate is:

```bash
make public-release-surface-smoke
```

That release gate adds NPM and Docker checks and must pass before any directory
submission claims those surfaces are live.

Publishing is orchestrated by `.github/workflows/publish-everywhere.yml`. The
workflow calls:

```bash
make release RELEASE_APPLY=1
```

`make release` is the CI release transaction. It runs `make release-check` once,
then calls `make publish-everywhere` with preflight reuse enabled. The lower
level `publish-everywhere` target remains available for retry recovery, but the
workflow does not call it directly.

`make release-check RELEASE_VERSION=<semver>` is the local pre-push contract.
It refuses to run without an explicit version unless GitHub Actions supplied a
`v<semver>` release ref. It verifies version alignment, runs the publish
preflight, and checks directory, MCPB, and Smithery metadata before a release
tag or GitHub release is created.

The release transaction publishes PyPI first, then fans out NPM, Docker Hub,
GHCR, MCP Registry metadata, and the Homebrew tap formula in one CI run. Tag
pushes do not publish; the GitHub Release publication is the single normal
release event. There are no per-registry publish workflows. Recovery runs the
same `publish-everywhere` workflow with the same Makefile orchestrator.

The orchestrator is retry-aware for partially completed releases. It checks the
PyPI package version, NPM package version, MCP Registry metadata, and Homebrew
formula state before submitting, so a rerun can recover after one registry
fails without treating already-published surfaces as fatal.

Before tagging a release, set the version everywhere and run:

```bash
make release-check RELEASE_VERSION=<semver>
```

That target includes `make release-gate`, so the dependency refresh, coverage,
package checks, release smoke, and mutation run in the release preflight.
Mutation evidence is written under `var/quality/mutation_stats.json`.

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

The public tap points to the PyPI `1.1.1` source artifact. Future releases
update the formula through `make publish-everywhere` with the
`HOMEBREW_TAP_TOKEN` GitHub Actions secret.

## NPM

NPM is an optional bridge package. It is for users who expect an `npx` command,
but the Python package remains the runtime source of truth.

The NPM package name is:

```text
@navinagrawal/mcp-broker
```

Do not publish the unscoped `mcp-broker` package name on NPM. That name already
belongs to a different project.

NPM trusted publishing is the preferred auth path. The publish workflow should
use GitHub Actions OIDC from the public repo and should publish only on GitHub
release `published`, manual dispatch, or repository dispatch events.

Details live in `docs/npm-distribution.md`.

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
- Run `.github/workflows/publish-everywhere.yml`. Do not publish the MCP
  Registry through a workflow-run chain after PyPI; the one-shot workflow owns
  the release.

GitHub OIDC is the preferred auth path. The workflow runs:

```bash
mcp-publisher login github-oidc
cp registry/server.json server.json
mcp-publisher publish
```

PyPI package must exist first. The MCP Registry validates that the public
package matches the server metadata before accepting the entry.

`1.1.1` is published after PyPI publication and the registry marks `1.1.1` as
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
  DOCKER_IMAGE=docker.io/navinagrawal/mcp-broker:1.1.1 \
  DOCKER_PLATFORMS=linux/amd64,linux/arm64 \
  DOCKER_PUSH=1
```

Docker Hub is the primary image for Docker MCP Catalog work:

```text
docker.io/navinagrawal/mcp-broker
```

GHCR is a mirror:

```text
ghcr.io/navinagrawal/mcp-broker
```

Recommended release tags for `1.1.1`:

```text
1.1.1
1.1
```

Do not publish `latest` until the maintainer confirms the tag should track the
newest stable release.

For a local one-platform buildx check without pushing:

```bash
make docker-buildx DOCKER_PLATFORMS=linux/arm64
```

Docker MCP Toolkit custom catalog smoke uses file-based server metadata:

```bash
make docker-mcp-catalog-smoke
```

The metadata file lives at:

```text
docker/mcp-catalog/mcp-broker.yaml
```

The Docker image itself is not treated as self-describing for Docker MCP
Toolkit. Docker's file-based catalog metadata path is the local validation path
until the official Docker registry review decides whether Docker builds the
catalog image or accepts the self-provided Docker Hub image.

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
- Completed before Docker MCP Catalog PR approval: public image publication and
  Docker-specific security review. Local Docker MCP Toolkit custom catalog smoke
  is covered by `make docker-mcp-catalog-smoke`.

Docker MCP Catalog submission uses the Docker registry PR flow after the
public repo contains the Dockerfile. The staged PR packet is
`docs/docker-mcp-registry-submission.md`.

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
make mcpb-pack
make mcpb-smoke
make mcpb-stdio-smoke
make smithery-payload-check
make directory-submission-check
```

Smithery uses the local MCPB path for this release. The hosted or remote path
waits until `mcp-broker` has a real streamable HTTP broker mode. The MCPB
manifest stays valid for Claude Desktop with rich descriptions only; MCPB does
not allow tool `inputSchema` fields. `make smithery-publish` sends a
Smithery-specific server-card payload and injects the source-backed broker
facade schemas for `broker_search_tools`, `broker_describe_tool`,
`broker_call_tool`, and `broker_status`. The first accepted Smithery release
returned deployment `aae18669-9500-4a5d-9870-8f9b3bfd404d` and MCP URL
`https://mcp-broker--navinagrawal.run.tools`; public search indexing may lag.

Glama lists the public repo at
`https://glama.ai/mcp/servers/NavinAgrawal/mcp-broker`. PulseMCP has also appeared from the registry/server.json surface at `https://www.pulsemcp.com/servers/navinagrawal-mcp-broker`. Check that tool names, schemas,
install instructions, safety notes, license, GitHub links, and score output
render correctly before adding secondary directories. The root `glama.json`
keeps Glama claim metadata public and points maintainer ownership to
`NavinAgrawal`.

Directory copy lives in:

```text
docs/directory-submission-packet.md
```

Before any directory submission, run `make directory-submission-check`. It
validates the packet, `/.well-known/mcp/server-card.json`,
`registry/server.json`, `glama.json`, and the MCPB manifest together so
directory pages cannot drift from the package metadata.

The public launch page lives in:

```text
docs/launch.md
```
