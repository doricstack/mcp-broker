# @doricstack/mcp-broker

NPM bridge for `mcp-broker`.

This package does not reimplement the Python broker in Node. It delegates to
the Python package with `uvx`:

```bash
npx @doricstack/mcp-broker --help
```

The Python package remains the runtime source of truth for broker behavior,
configuration, profile gates, and MCP client rendering.

Primary install paths remain PyPI and Homebrew:

```bash
pipx install mcp-broker
brew install doricstack/tap/mcp-broker
```
