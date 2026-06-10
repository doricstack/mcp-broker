# Changelog

All notable public changes will be recorded here.

## 1.4.0 - 2026-06-10

- Synchronize release metadata through the Makefile release path.

## 1.3.1 - 2026-06-07

- Synchronize release metadata through the Makefile release path.

## 1.3.0 - 2026-06-06

- Add the production `mcp-broker` brand asset kit, README header, and branding
  rules contract for public repo surfaces.
- Add client cwd based profile routing so a broker request can route to the
  profile that owns the active project root.
- Add runtime secrets sync before broker startup so LaunchAgent-owned daemons
  can read configured secret files without inheriting shell environment.
- Filter selected broker catalog listing by upstream metadata and tool prefix
  so targeted broker searches avoid listing irrelevant slow upstreams.

## 1.2.0 - 2026-05-29

- Add per-tool upstream call timeouts so long-running brokered tools can get
  more time without loosening the default timeout for every tool on an upstream.

## 1.1.3 - 2026-05-28

- Synchronize release metadata through the Makefile release path.

## 1.1.2 - 2026-05-28

- Add source-backed broker facade tool descriptions and schemas for Glama,
  Smithery, Claude Desktop MCPB, and other directory scanners.
- Add `make release` as the CI release transaction so release publication runs
  one version-aware target before publishing all registry surfaces.
- Add `make release-check RELEASE_VERSION=<semver>` as the local pre-push
  release gate for version alignment, package checks, directory metadata, MCPB,
  and Smithery payload validation.

## 1.1.1 - 2026-05-27

- Fix MCPB and Claude Desktop stdio startup when the broker daemon is already
  running.
- Add a Smithery MCPB release adapter that preserves the valid Claude Desktop
  manifest while publishing Smithery server-card tool schemas.
- Add a configurable MCPB `UVX command path` for GUI environments that cannot
  find `uvx` from shell PATH.

## 1.1.0 - 2026-05-26

- Add the one-shot `make publish-everywhere` CI release path for PyPI, NPM,
  Docker Hub, GHCR, and MCP Registry publication.
- Add the scoped NPM bridge package at `${NPM_PACKAGE_NAME}`.
- Add Docker Hub primary and GHCR mirror publication contracts for the Docker
  image release path.

## 1.0.0 - 2026-05-26

- Promote the public release line from pre-1.0 packages to the first stable
  release.
- Align package, registry, MCPB, server-card, Homebrew, and public release
  documentation on `1.0.0`.
- Keep `0.1.x` entries as pre-1.0 public history instead of deleting published
  artifacts.

## 0.1.2 - 2026-05-26

- Harden mutation-gate coverage for configuration, profile validation, project
  MCP import, daemon helpers, upstream lifecycle, and runtime cleanup paths.
- Remove mutation skip comments and require zero survived, untested, skipped,
  suspicious, timeout, interrupted, segfault, or unchecked mutants for release.
- Keep public export and maintainer release gates green with 100% coverage and
  100% mutation score.

## 0.1.1 - 2026-05-25

- Correct MCP Registry namespace casing in package README, registry metadata,
  and server card so GitHub OIDC ownership validation matches PyPI metadata.

## 0.1.0 - 2026-05-25

- Local MCP broker daemon with a compact MCP facade.
- Stdio client shim for Codex and Claude Code.
- Strict YAML config contract with JSON Schema validation.
- Profile-scoped upstream exposure and mutating-tool allowlists.
- Shared and per-session upstream process management.
- Runtime state under the user's broker runtime root, outside the repo.
- macOS LaunchAgent, Linux systemd user service, and Windows Scheduled Task
  install flows with dry-run defaults.
- Public smoke, quality, release, and export gates.
- Context reduction evidence in `docs/context-reduction-measurement.md`.
