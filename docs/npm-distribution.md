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
mcp-broker==1.1.1
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
- Permission: publish

As of 2026-05-27, `@navinagrawal/mcp-broker@1.1.0` is published and the package
has a GitHub Actions trusted publisher for `publish-everywhere.yml`. The release
workflow uses OIDC for future NPM publications and does not require a long-lived
NPM registry token.

## Release Policy

The current source release is `1.1.1`. It is a patch release for the Claude
Desktop MCPB stdio startup path and Smithery MCPB adapter. The NPM and Docker
distribution paths were introduced in `1.1.0`.

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
