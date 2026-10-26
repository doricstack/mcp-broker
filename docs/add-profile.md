# Add a New LLM Profile

Use a profile when a client should see a different broker tool budget, upstream
set, or mutating-tool policy. Do not copy another client config by hand. Generate
the starter block, paste it into your YAML, then add the profile name only to the
upstreams that client should see.

## 1. Generate the starter block

For clients that store MCP servers under top-level `mcpServers`:

```bash
make profile-snippet NEW_PROFILE=my-llm NEW_CLIENT_FORMAT=mcp-settings-json
```

For TOML clients using the Codex config shape:

```bash
make profile-snippet NEW_PROFILE=my-llm NEW_CLIENT_FORMAT=codex-toml
```

For JSON clients using the Claude config shape:

```bash
make profile-snippet NEW_PROFILE=my-llm NEW_CLIENT_FORMAT=claude-json
```

Optional inputs:

```bash
make profile-snippet \
  NEW_PROFILE=my-llm \
  NEW_CLIENT_FORMAT=mcp-settings-json \
  NEW_CLIENT_CONFIG_PATH='$HOME/.my-llm/settings.json' \
  NEW_CLIENT_ENTRY_NAME=mcp-broker \
  NEW_CLIENT_COMMAND=mcp-broker-client \
  NEW_BROKER_TOOL_NAME_STYLE=snake
```

## 2. Add the profile block

Paste the generated `profiles:` entry into `config/broker.private.yaml`:

```yaml
profiles:
  my-llm:
    max_tools: 80
    compact_tools_enabled: true
    broker_tool_name_style: dotted
```

Use compact mode unless the client can accept the full upstream tool list. Use
`broker_tool_name_style: snake` when a client does not expose dotted MCP tool
names. For example, that renders `broker.status` as `broker_status` while the
broker still accepts the canonical dotted name.

### Result size settings

Two optional settings size tool results for the client behind the profile. Both
take a positive integer number of characters and are off when left out.

```yaml
profiles:
  claude:
    max_tools: 80
    compact_tools_enabled: true
    result_size_chars: 200000
    result_budget_chars: 45000
```

`result_size_chars` raises the size of text result the client keeps inline from
`broker_call_tool`. The broker adds
`"_meta": {"anthropic/maxResultSizeChars": <value>}` to the `broker_call_tool`
entry in `tools/list`; the other broker tools are unchanged. Claude Code saves
a text result over 50,000 characters to a file unless the tool declares this
field, and honors it up to 500,000, so the broker rejects larger values. Clients
that do not read the field ignore it.

`result_budget_chars` tells upstreams how large an answer the client can take.
Every `tools/call` the broker forwards to a stdio or HTTP upstream carries
`params._meta["mcp-broker/result_budget_chars"] = <value>`, merged with any
metadata the upstream's `forward_request_meta` allowlist passes through. The
profile value wins over a caller-supplied field of the same name, and
configured `request_meta` credentials still win over both. Upstreams that do
not read `_meta` behave exactly as before. Set it a little under the client's
limit, for example about 45,000 for Claude Code's 50,000 default, or lower for
a client that truncates around 10,000 tokens.

Config load fails on zero, negatives, non-integers, `true`/`false`, and on a
`result_size_chars` above 500,000.

## 3. Add the client render block

Paste the generated `clients:` entry into the same YAML:

```yaml
clients:
  my-llm:
    format: mcp-settings-json
    config_path: $HOME/.my-llm/settings.json
    entry_name: mcp-broker
    command: mcp-broker-client
    mcp_allowed_servers:
      - mcp-broker
    args:
      - --socket-path
      - "{runtime.socket_path}"
      - --profile
      - my-llm
```

The renderer replaces `{runtime.socket_path}` from the central `runtime` block.
The client shim expands `$HOME` and `~` at runtime, so rendered configs can stay
portable.

For `mcp-settings-json` clients, keep `mcp_allowed_servers` set to the broker
entry name. Some clients connect to a configured stdio server but do not expose
its tools to model-facing sessions until the server is present in the MCP
allowlist.

For a `codex-toml` client, `tool_output_token_limits` maps a broker tool name to
the token budget Codex keeps for that tool's result. Codex otherwise cuts the
middle out of any result past the model's truncation budget (10,000 tokens on
current models). The renderer writes one
`[mcp_servers."<entry_name>".tools.<tool>]` table per entry, holding
`output_token_limit`:

```yaml
    tool_output_token_limits:
      broker_call_tool: 16000
```

## 4. Choose upstream exposure

Add the new profile name to each upstream that should be visible:

```yaml
upstreams:
  example-store:
    profiles:
      - codex
      - claude
      - agy
      - my-llm
```

Do not expose everything by default. Start with read-only upstreams, then add
mutating upstreams only after the profile allowlist is set.

## 5. Validate before rendering

Every enabled upstream visible to the profile needs a `smoke` probe:

```bash
make config-validate CONFIG_PATH=config/broker.private.yaml
make profile-validation PROFILE=my-llm
```

Fix missing probes before wiring the client.

## 6. Render, inspect, apply

```bash
make config-render CLIENT=my-llm CONFIG_RENDER_APPLY=0
make config-render CLIENT=my-llm CONFIG_RENDER_APPLY=1
```

The dry run writes under `$HOME/mcp/mcp-broker/renders/`. Apply writes the client
config and stores a backup under `$HOME/mcp/mcp-broker/backups/`.

## 7. Smoke the broker facade

```bash
make facade-smoke PROFILE=my-llm
```

If no explicit `FACADE_CALL_TOOL` is provided, this target selects the first
callable YAML `smoke` probe visible to the profile. That keeps the target generic
and avoids hardcoded private MCP names.

## 8. Restart the client

Restart the LLM client after rendering. Most clients load MCP config only at
process start.
