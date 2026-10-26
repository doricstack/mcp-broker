"""Per-tool output token limits rendered into Codex's config.

Codex cuts the middle out of an MCP tool result past the model's truncation
budget (10,000 tokens on the current models). A client may raise it per tool
with `mcp_servers.<id>.tools.<tool>.output_token_limit`; the broker owns the
`mcp_servers` tables in Codex's config, so it has to render that table itself.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from mcp_broker.config import BrokerConfig
from mcp_broker.config_render import render_client_config


def _write_config(tmp_path: Path, client_block: str, *, fmt: str = "codex-toml") -> Path:
    config_path = tmp_path / "broker.yaml"
    target = tmp_path / ("codex.toml" if fmt == "codex-toml" else "client.json")
    config_path.write_text(
        f"""
runtime:
  root: {tmp_path}/runtime
clients:
  codex:
    format: {fmt}
    config_path: {target}
    entry_name: mcp-broker
    command: mcp-broker-client
    args: ["--profile", "codex"]
{client_block}
upstreams: {{}}
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _render(config_path: Path) -> str:
    result = render_client_config(BrokerConfig.from_file(config_path), client_name="codex", dry_run=True)
    return result.rendered_path.read_text(encoding="utf-8")


def test_codex_render_writes_one_tools_table_per_limit(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        "    tool_output_token_limits:\n      broker_search_tools: 12000\n      broker_call_tool: 40000\n",
    )

    rendered = _render(config_path)
    parsed = tomllib.loads(rendered)

    server = parsed["mcp_servers"]["mcp-broker"]
    assert server["command"] == "mcp-broker-client"
    assert server["tools"] == {
        "broker_call_tool": {"output_token_limit": 40000},
        "broker_search_tools": {"output_token_limit": 12000},
    }
    assert rendered.index("broker_call_tool") < rendered.index("broker_search_tools")


def test_codex_render_rerender_replaces_old_tools_tables(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, "    tool_output_token_limits:\n      broker_call_tool: 40000\n")
    target = tmp_path / "codex.toml"
    target.write_text(
        'model = "x"\n\n'
        '[mcp_servers."mcp-broker"]\ncommand = "old"\nargs = []\n\n'
        '[mcp_servers."mcp-broker".tools.broker_call_tool]\noutput_token_limit = 9\n',
        encoding="utf-8",
    )

    rendered = _render(config_path)
    parsed = tomllib.loads(rendered)

    assert parsed["model"] == "x"
    assert parsed["mcp_servers"]["mcp-broker"]["tools"] == {"broker_call_tool": {"output_token_limit": 40000}}
    assert rendered.count("output_token_limit") == 1
    assert "command = \"old\"" not in rendered


def test_codex_render_without_limits_writes_no_tools_table(tmp_path: Path) -> None:
    rendered = _render(_write_config(tmp_path, ""))

    parsed = tomllib.loads(rendered)
    assert "tools" not in parsed["mcp_servers"]["mcp-broker"]
    assert "output_token_limit" not in rendered
    assert parsed["mcp_servers"]["mcp-broker"]["args"] == ["--profile", "codex"]


def test_codex_render_quotes_a_tool_name_that_is_not_a_bare_key(tmp_path: Path) -> None:
    rendered = _render(_write_config(tmp_path, "    tool_output_token_limits:\n      broker.call_tool: 20000\n"))

    parsed = tomllib.loads(rendered)
    assert parsed["mcp_servers"]["mcp-broker"]["tools"] == {"broker.call_tool": {"output_token_limit": 20000}}
    assert '.tools."broker.call_tool"]' in rendered


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ("    tool_output_token_limits: 5\n", "tool_output_token_limits must be a mapping"),
        ("    tool_output_token_limits:\n      broker_call_tool: 0\n", "must be a positive integer"),
        ("    tool_output_token_limits:\n      broker_call_tool: -3\n", "must be a positive integer"),
        ("    tool_output_token_limits:\n      broker_call_tool: true\n", "must be a positive integer"),
        ("    tool_output_token_limits:\n      broker_call_tool: '900'\n", "must be a positive integer"),
        ("    tool_output_token_limits:\n      '': 900\n", "tool name must be a non-empty string"),
    ],
)
def test_bad_tool_output_token_limits_are_refused(tmp_path: Path, block: str, message: str) -> None:
    config_path = _write_config(tmp_path, block)

    with pytest.raises(ValueError, match=message) as error:
        BrokerConfig.from_file(config_path)

    assert "clients.codex.tool_output_token_limits" in str(error.value)


def test_tool_output_token_limits_are_refused_on_a_non_codex_client(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        "    tool_output_token_limits:\n      broker_call_tool: 900\n",
        fmt="claude-json",
    )

    with pytest.raises(ValueError, match="only to a codex-toml client") as error:
        BrokerConfig.from_file(config_path)

    assert "clients.codex.tool_output_token_limits" in str(error.value)
