# Community Launch

Use this checklist after the clean public repo and first release exist.

## Channels

- GitHub Discussions: post the demo issue, context-reduction measurement, and
  install path.
- Hacker News: use a concise technical launch post. Lead with the problem:
  local MCP clients load too many tools and too much serialized tool context.
- Reddit `r/mcp`: focus on MCP config, profile gates, and upstream compatibility.
- Reddit `r/LocalLLaMA`: focus on local control, reduced tool load, and keeping
  auth state under user-owned runtime paths.
- MCP Discord or Slack communities: share the repo, release notes, and one demo
  trace. Do not cross-post the same text everywhere.

## Feedback Labels

Create feedback labels before external posts go live.

Create labels in the public repo before posting:

- `install failure`
- `client compatibility`
- `upstream compatibility`
- `auth`
- `security`
- `documentation`
- `first-user feedback`

## First-Response Rules

- Ask for OS, Python version, install method, client, and sanitized config
  snippet on install issues.
- Ask for the upstream transport, package, auth method, and smoke probe on
  upstream compatibility issues.
- Do not ask users to post tokens, browser profiles, database URLs, or private
  filesystem paths.
- Convert repeated failures into tests before changing docs.
