# Context reduction measurement

Measured on 2026-05-24.

This document backs the context reduction claim with local evidence. It measures tool definitions and serialized tool-definition tokens that a Codex session would load before the user asks a task.

## Result

| Surface | Before | After | Reduction |
|---|---:|---:|---:|
| Direct Codex MCP server entries | 11 | 1 | 90.91% |
| MCP tool definitions, raw upstreams versus broker facade | 414 | 4 | 99.03% |
| Hosted `codex_apps` tool definitions | 195 | 39 | 80.00% |
| Combined always-loaded tool definitions | 609 | 43 | 92.94% |

The headline should distinguish count reduction from token reduction:

- Tool-definition count: 609 to 43, a 92.94% reduction.
- Serialized token count with `tiktoken` `o200k_base`: 276,989 to 45,281, an 83.65% reduction.
- Serialized token count with `tiktoken` `cl100k_base`: 272,802 to 44,778, an 83.59% reduction.

Combined tool-count formula:

```text
before = 414 raw MCP tools + 195 codex_apps tools = 609
after = 4 broker facade tools + 39 remaining codex_apps tools = 43
reduction = (609 - 43) / 609 * 100 = 92.94%
```

Combined `o200k_base` token formula:

```text
before = 125,211 raw MCP tool tokens + 151,783 codex_apps tool tokens = 276,989
after = 167 broker facade tool tokens + 45,119 remaining codex_apps tool tokens = 45,281
reduction = (276,989 - 45,281) / 276,989 * 100 = 83.65%
```

## What Changed

Before this broker setup, Codex was configured with 11 direct MCP server entries. After broker rendering, Codex has one local MCP entry: `mcp-broker`.

The broker then exposes four compact facade tools:

- `broker_search_tools`
- `broker_describe_tool`
- `broker_call_tool`
- `broker_status`

The upstream MCPs are still reachable. They are no longer all placed in the model's first tool view.

## Evidence

Direct Codex MCP entries:

- Before: local backup evidence contains 11 direct `mcp_servers` entries.
- After: the rendered local client config contains 1 `mcp_servers` entry, `mcp-broker`.

Current compact broker count:

```bash
make tools-count PROFILE=codex
```

Token count for the compact broker payload:

| Payload | Tools | Bytes | `o200k_base` tokens | `cl100k_base` tokens |
|---|---:|---:|---:|---:|
| Compact broker facade | 4 | 783 | 167 | 161 |

Result:

```json
{
  "profile": "codex",
  "total_tools": 4,
  "upstream_counts": {"broker": 4},
  "tools": [
    "broker_call_tool",
    "broker_describe_tool",
    "broker_search_tools",
    "broker_status"
  ]
}
```

Current raw MCP counterfactual:

- A temporary in-memory profile was created from `config/broker.private.yaml`.
- The temporary profile used the same enabled Codex upstreams.
- `compact_tools_enabled` was set to `false`.
- `tools/list` included `broker_session_id=measure-session` so session-bound upstreams could list tools.
- No client config was rendered or written for this measurement.

Result:

| Configured upstream | Raw tools |
|---|---:|
| Upstream 01 | 14 |
| Upstream 02 | 3 |
| Upstream 03 | 18 |
| Upstream 04 | 42 |
| Upstream 05 | 6 |
| Upstream 06 | 9 |
| Upstream 07 | 225 |
| Upstream 08 | 9 |
| Upstream 09 | 11 |
| Upstream 10 | 25 |
| Upstream 11 | 15 |
| Upstream 12 | 2 |
| Upstream 13 | 23 |
| Upstream 14 | 12 |
| **Total** | **414** |

Token count for the raw MCP payload:

| Payload | Tools | Bytes | `o200k_base` tokens | `cl100k_base` tokens |
|---|---:|---:|---:|---:|
| Raw current-config MCP tools | 414 | 406,283 | 125,211 | 124,973 |

MCP-only reduction:

| Metric | Before raw MCP | After broker facade | Reduction |
|---|---:|---:|---:|
| Tool definitions | 414 | 4 | 99.03% |
| `o200k_base` tokens | 125,211 | 167 | 99.87% |
| `cl100k_base` tokens | 124,973 | 161 | 99.87% |

Hosted `codex_apps` evidence:

- Before policy: local backup evidence contains 195 hosted app tools.
- After policy: the current hosted app cache contains 39 hosted app tools.
- The policy removed duplicate hosted connectors already owned by the broker.

Token count for hosted `codex_apps` payloads:

| Payload | Tools | Bytes | `o200k_base` tokens | `cl100k_base` tokens | Reduction |
|---|---:|---:|---:|---:|---:|
| Before policy | 195 | 619,899 | 151,783 | 147,833 | - |
| After policy | 39 | 185,105 | 45,119 | 44,621 | 70.27% by `o200k_base` tokens |

## Combined Token Measurement

The combined measurement uses the same canonical serialization for all payloads:

```python
json.dumps({"tools": tools}, sort_keys=True, separators=(",", ":"))
```

Tokenization used `tiktoken` with `o200k_base` as the primary encoding and `cl100k_base` as a comparison encoding.

| Combined payload | Tools | Bytes | `o200k_base` tokens | `cl100k_base` tokens |
|---|---:|---:|---:|---:|
| Before: raw MCP tools + pre-policy `codex_apps` | 609 | 1,026,171 | 276,989 | 272,802 |
| After: broker facade + post-policy `codex_apps` | 43 | 185,877 | 45,281 | 44,778 |
| Reduction | 92.94% | 81.89% | 83.65% | 83.59% |

## Interpretation

The broker cuts the always-loaded MCP tool surface from a large raw list to a four-tool map. The `codex_apps` policy removes hosted duplicates that would otherwise still compete for the same model attention.

This is not proof that every task becomes faster or better. It is proof that the always-loaded tool-definition count was reduced by 92.94%, and the serialized combined tool payload dropped by 83.65% under `o200k_base`, in this measured Codex setup.

That matters because long-context models still have placement sensitivity. A smaller front-loaded tool map keeps the task, repo instructions, and recent user request out of a crowded middle section.

## Caveats

- The 414 raw MCP tool count is a current-config counterfactual, not an archived pre-broker `/mcp` payload. The archived pre-broker config proves 11 direct MCP entries; the current broker config has 14 enabled Codex-visible upstreams.
- Token counts use canonical minified JSON for tool payloads, not a captured Codex-internal prompt. The actual prompt serialization may differ.
- Hosted `codex_apps` availability can change when Codex refreshes hosted connectors. The policy hook exists so duplicate hosted connectors can be removed again after a refresh.
