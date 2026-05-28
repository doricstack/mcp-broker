# Docker MCP Registry Submission

Status: PR submitted and pending external Docker review.

PR: `https://github.com/docker/mcp-registry/pull/3819`

Current PR state checked on 2026-05-27: open, not draft, mergeable, blocked by
required review, and not mergeable by this maintainer token because
`docker/mcp-registry` grants only read permission.

## Package

- Public repository: `https://github.com/NavinAgrawal/mcp-broker`
- Primary image: `docker.io/navinagrawal/mcp-broker:$(PACKAGE_VERSION)`
- Mirror image: `ghcr.io/navinagrawal/mcp-broker:$(PACKAGE_VERSION)`
- Catalog metadata: `docker/mcp-catalog/mcp-broker.yaml`

## Runtime Boundary

- No hidden host client config writes.
- Runtime state, config, logs, and secrets require explicit mounts.
- Stdio upstreams are supported when the upstream command exists inside the
  container.
- HTTP, streamable HTTP, and SSE upstreams are the preferred Docker use case.
- The container entrypoint runs `mcp-broker stdio --init-if-missing`.

## Verification Packet

Run before PR submission:

```bash
make docker-smoke
make docker-mcp-catalog-smoke
make maintainer-violations
make maintainer-grade-quality
```

Run after image publication:

```bash
make docker-publish-check
make docker-release-smoke DOCKER_RELEASE_IMAGE=docker.io/navinagrawal/mcp-broker:$(PACKAGE_VERSION)
```

## Submission Path

Preferred path is Docker's `docker/mcp-registry` PR process. If Docker requires
a Docker-built image under the `mcp/` namespace, use this packet as the source
description and point the registry entry to the public GitHub repository.
