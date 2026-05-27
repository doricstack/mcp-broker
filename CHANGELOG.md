# Changelog

All notable public changes will be recorded here.

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
- Add the scoped NPM bridge package at `@navinagrawal/mcp-broker`.
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
