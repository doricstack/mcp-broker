# NPM Distribution

NPM is an optional bridge package for users who expect an `npx` install path.
It is not a second broker implementation.

## Package Name

`mcp-broker` on NPM is a different project. This repo must not publish the
unscoped NPM name.

The package for this project is:

```text
${NPM_PACKAGE_NAME}
```

Expected user command after publication:

```bash
npx ${NPM_PACKAGE_NAME} --help
```

## Runtime Contract

The NPM package is a thin Node wrapper. It delegates to the Python package:

```text
mcp-broker==${PACKAGE_VERSION}
```

The wrapper does not reimplement the Python broker in Node. The Python package
remains the runtime source of truth for config parsing, process lifecycle,
profile gates, client rendering, and broker stdio behavior.

The wrapper must not edit host Codex, Claude, AGY, Cursor, Windsurf, or LM Studio
config files unless the user invokes an explicit broker command that already
has that behavior in the Python CLI.

## Auth And Publication

NPM trusted publishing is the preferred auth path. It uses GitHub Actions OIDC
instead of a long-lived NPM token and publishes provenance for public packages
from public repositories.

Required package settings for trusted publishing:

- Package name: `${NPM_PACKAGE_NAME}`
- Visibility: public
- Trusted publisher: GitHub Actions
- Repository: `${GITHUB_REPO}`
- Workflow file: `.github/workflows/publish-everywhere.yml`
- Permission: publish

Current publication uses a scoped `NPM_TOKEN` secret because the package scope
does not have an OIDC trusted publisher configured yet. The workflow maps that
secret to `NODE_AUTH_TOKEN`, while `npm publish --provenance` still signs
provenance through the job's `id-token: write` permission.

Move back to trusted publishing once the package scope supports the
`.github/workflows/publish-everywhere.yml` publisher.

## Release Policy

The current source release comes from `${PACKAGE_VERSION}`. Set it with
`make release-version-sync RELEASE_VERSION=<semver>` or
`make release-version-sync RELEASE_BUMP=patch|minor|major` before tagging.

Do not publish an NPM package until all of these pass:

```bash
make release-check RELEASE_VERSION=<semver>
make public-export-check PUBLIC_REPO=$PUBLIC_REPO
```

Final publication happens through the one-shot CI release target:

```bash
make release RELEASE_APPLY=1
```

After publication, verify through Make:

```bash
make npm-release-smoke
```
