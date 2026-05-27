# NPM Distribution

NPM is an optional bridge package for users who expect an `npx` install path.
It is not a second broker implementation.

## Package Name

`mcp-broker` on NPM is a different project. This repo must not publish the
unscoped NPM name.

The package for this project is:

```text
@navinagrawal/mcp-broker
```

Expected user command after publication:

```bash
npx @navinagrawal/mcp-broker --help
```

## Runtime Contract

The NPM package is a thin Node wrapper. It delegates to the Python package:

```text
mcp-broker==1.1.0
```

The wrapper does not reimplement the Python broker in Node. The Python package
remains the runtime source of truth for config parsing, process lifecycle,
profile gates, client rendering, and broker stdio behavior.

The wrapper must not edit host Codex, Claude, Gemini, Cursor, Windsurf, or LM
Studio config files unless the user invokes an explicit broker command that
already has that behavior in the Python CLI.

## Auth And Publication

NPM trusted publishing is the preferred auth path. It uses GitHub Actions OIDC
instead of a long-lived NPM token and publishes provenance for public packages
from public repositories.

Required package settings for trusted publishing:

- Package name: `@navinagrawal/mcp-broker`
- Visibility: public
- Trusted publisher: GitHub Actions
- Repository: `NavinAgrawal/mcp-broker`
- Workflow file: `.github/workflows/publish-everywhere.yml`

Use `NPM_TOKEN` only as a fallback if trusted publishing cannot be configured
for the first publication. The GitHub workflow passes `NODE_AUTH_TOKEN` from
that secret when it exists, while still allowing npm trusted publishing through
OIDC.

As of 2026-05-27, npm trusted publishing reached the publish step but the first
publish returned `E404` for `@navinagrawal/mcp-broker@1.1.0`. PyPI, Docker Hub,
GHCR, and MCP Registry completed in the same release run. The next retry needs
an npm granular automation token with package publish permission stored as the
GitHub Actions secret `NPM_TOKEN`, or an npm package bootstrap that lets trusted
publishing attach to the package settings.

## Release Policy

The next distribution release is `1.1.0`. That version adds NPM and Docker
distribution paths, so it is a minor release, not a patch release.

Do not publish an NPM package until all of these pass:

```bash
make publish-everywhere-check
make public-export-check PUBLIC_REPO=$PUBLIC_REPO
```

Final publication happens through the one-shot CI workflow:

```bash
make publish-everywhere PUBLISH_EVERYWHERE_APPLY=1
```

After publication, verify through Make:

```bash
make npm-release-smoke
```
