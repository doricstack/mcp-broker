# Security Policy

`mcp-broker` is local developer infrastructure. Treat every upstream MCP as
code you are choosing to run on your machine or call with your credentials.

## Supported Versions

Security fixes target the current `main` branch and the current `1.x` stable
release line.

## Reporting A Vulnerability

Open a private security advisory on GitHub once the public repository is live.
Until then, report issues through the maintainer-controlled private channel for
this project.

Do not paste tokens, OAuth refresh values, database URLs with passwords, or
private MCP inventories into an issue.

## Security Boundaries

Secrets belong in environment variables or runtime secret files referenced from
`config/broker.private.yaml`. The repo must not contain secret values.

OAuth state, browser state, socket files, logs, rendered client configs, and
backups belong under the runtime root, not in git.

Sensitive mutating tools must be marked with `mutating: true` and exposed only through
per-profile allowlists. Use `serialize_calls: true` or `per_session` for tools
that write to shared accounts, shared files, browser state, filesystem roots,
or database URLs.

Filesystem roots, database URLs, cloud deploy tools, and browser automation
need narrow profiles. Do not expose them to every client by default.

## Required Local Checks

Run these before release or public export:

```bash
make quality-gate
make config-validate
make broker-smoke
make public-export-check
```

See `docs/security-review.md` and `docs/security-model.md` for the full threat
model and release gate.
