# Docker MCP Registry Submission

Status: PR submitted and pending external Docker review.

PR: `${DOCKER_MCP_CATALOG_PR_URL}`

Current PR state checked on 2026-05-28: open, not draft, `REVIEW_REQUIRED`,
`mergeStateStatus=BLOCKED`, no review comments, and not mergeable by this
maintainer token because `docker/mcp-registry` grants only read permission.

## Package

- Public repository: `${GITHUB_REPOSITORY_URL}`
- Primary image: `${DOCKER_REPOSITORY_IMAGE}:${PACKAGE_VERSION}`
- Mirror image: `${GHCR_REPOSITORY_IMAGE}:${PACKAGE_VERSION}`
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
make docker-release-smoke DOCKER_RELEASE_IMAGE=${DOCKER_REPOSITORY_IMAGE}:${PACKAGE_VERSION}
```

## Submission Path

Preferred path is Docker's `docker/mcp-registry` PR process. If Docker requires
a Docker-built image under the `mcp/` namespace, use this packet as the source
description and point the registry entry to the public GitHub repository.
