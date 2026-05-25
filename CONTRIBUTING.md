# Contributing

## Public repo first

Every change must work for a user who cloned this repo on a clean machine.
Do not commit local MCP inventory, host-specific paths, private workflow notes,
OAuth state, logs, rendered client configs, sockets, or backup files.

Use `config/broker.example.yaml` for public examples. Keep real upstreams in
`config/broker.private.yaml`, which is ignored by git.

## Development Setup

```bash
make setup
make config-validate
make test
```

Use Makefile targets for build, test, install, and smoke flows. If a new public
command is needed, add a Makefile target and test it.

## Required Checks

Before a pull request:

```bash
make precommit
make quality-gate
make public-export-check
```

Maintainers may also run private local gates, but public contributors should
not need private scripts outside this repository.

## Config Changes

When changing config behavior:

- Update `config/broker.example.yaml`.
- Update `config/broker.schema.json`.
- Add tests for valid and invalid shapes.
- Keep comments generic and user-editable.
- Never copy private config values into tests or docs.

## Security-Sensitive Changes

For mutating tools, OAuth state, browser state, filesystem roots, database
URLs, or profile allowlists, update `SECURITY.md` and the security docs with
the user-facing risk.

## Pull Requests

Keep changes scoped. Include the tests you ran and the public behavior that
changed. Do not include private session history or maintainer-only notes.
