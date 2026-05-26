import json
from pathlib import Path

import pytest
import yaml


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_deferred_acceptance_plan_is_profile_driven(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.deferred_acceptance import build_deferred_acceptance_plan

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_acceptance_config(tmp_path), sort_keys=True), encoding="utf-8")

    report = build_deferred_acceptance_plan(BrokerConfig.from_file(config_path), "llm")

    assert report["profile"] == "llm"
    assert report["upstream_count"] == 2
    assert report["deferred_wrapper_namespace"] == "mcp__mcp_broker__"
    assert report["external_llm_required"] is True
    assert report["acceptance_scope"] == (
        "Run these calls from inside an active LLM client session where the mcp-broker "
        "deferred tools are available. This is not a public quality-gate input."
    )
    assert [upstream["upstream"] for upstream in report["upstreams"]] == ["callable", "search-only"]
    assert [upstream["call_enabled"] for upstream in report["upstreams"]] == [True, False]
    assert report["upstreams"][0]["steps"] == [
        {
            "step": "search",
            "client_wrapper": "mcp__mcp_broker__.broker_search_tools",
            "arguments": {"query": "callable status", "limit": 100},
        },
        {
            "step": "describe",
            "client_wrapper": "mcp__mcp_broker__.broker_describe_tool",
            "arguments": {"name": "callable.status"},
        },
        {
            "step": "call",
            "client_wrapper": "mcp__mcp_broker__.broker_call_tool",
            "arguments": {"name": "callable.status", "arguments": {"scope": "demo"}},
        },
    ]
    assert report["upstreams"][1]["steps"][-1] == {
        "step": "call",
        "skipped": True,
        "reason": "smoke.call is false",
    }


def test_deferred_acceptance_plan_rejects_profile_upstreams_without_smoke(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.deferred_acceptance import build_deferred_acceptance_plan

    data = _acceptance_config(tmp_path)
    data["upstreams"]["missing-smoke"] = {
        "command": "missing-smoke",
        "enabled": True,
        "mode": "shared",
        "profiles": ["llm"],
    }
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="llm missing smoke probes: missing-smoke"):
        build_deferred_acceptance_plan(BrokerConfig.from_file(config_path), "llm")


def test_deferred_acceptance_plan_sorts_missing_smoke_names(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.deferred_acceptance import build_deferred_acceptance_plan

    data = _acceptance_config(tmp_path)
    for name in ["z-missing", "a-missing"]:
        data["upstreams"][name] = {
            "command": name,
            "enabled": True,
            "mode": "shared",
            "profiles": ["llm"],
        }
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        build_deferred_acceptance_plan(BrokerConfig.from_file(config_path), "llm")

    assert str(exc_info.value) == "llm missing smoke probes: a-missing, z-missing"


def test_deferred_acceptance_markdown_lists_wrapper_calls(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.deferred_acceptance import build_deferred_acceptance_plan, render_markdown

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_acceptance_config(tmp_path), sort_keys=True), encoding="utf-8")

    markdown = render_markdown(build_deferred_acceptance_plan(BrokerConfig.from_file(config_path), "llm"))

    assert markdown == (
        "# Deferred Tool Acceptance\n"
        "\n"
        "Profile: `llm`\n"
        "Upstreams: `2`\n"
        "\n"
        "Run these calls from inside an active LLM client session where the mcp-broker "
        "deferred tools are available. This is not a public quality-gate input.\n"
        "\n"
        "## callable\n"
        "\n"
        "Smoke tool: `callable.status`\n"
        "Search query: `callable status`\n"
        "\n"
        "- `mcp__mcp_broker__.broker_search_tools` with `{\"limit\": 100, \"query\": \"callable status\"}`\n"
        "- `mcp__mcp_broker__.broker_describe_tool` with `{\"name\": \"callable.status\"}`\n"
        "- `mcp__mcp_broker__.broker_call_tool` with `{\"arguments\": {\"scope\": \"demo\"}, \"name\": \"callable.status\"}`\n"
        "\n"
        "## search-only\n"
        "\n"
        "Smoke tool: `search-only.lookup`\n"
        "Search query: `search only`\n"
        "\n"
        "- `mcp__mcp_broker__.broker_search_tools` with `{\"limit\": 100, \"query\": \"search only\"}`\n"
        "- `mcp__mcp_broker__.broker_describe_tool` with `{\"name\": \"search-only.lookup\"}`\n"
        "- `call` skipped: smoke.call is false\n"
    )


def test_deferred_acceptance_markdown_continues_after_skipped_step() -> None:
    from mcp_broker.deferred_acceptance import render_markdown

    markdown = render_markdown(
        {
            "profile": "llm",
            "upstream_count": 1,
            "acceptance_scope": "manual broker acceptance",
            "upstreams": [
                {
                    "upstream": "deferred",
                    "tool": "deferred.lookup",
                    "query": "deferred lookup",
                    "steps": [
                        {
                            "step": "call",
                            "skipped": True,
                            "reason": "smoke.call is false",
                        },
                        {
                            "step": "describe",
                            "client_wrapper": "mcp__mcp_broker__.broker_describe_tool",
                            "arguments": {"name": "deferred.lookup"},
                        },
                    ],
                }
            ],
        }
    )

    assert (
        "- `call` skipped: smoke.call is false\n"
        "- `mcp__mcp_broker__.broker_describe_tool` with `{\"name\": \"deferred.lookup\"}`\n"
    ) in markdown


def test_deferred_acceptance_main_outputs_markdown_and_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deferred_acceptance import main

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_acceptance_config(tmp_path), sort_keys=True), encoding="utf-8")

    assert main(["--config", str(config_path), "--profile", "llm", "--format", "markdown"]) == 0
    captured = capsys.readouterr()
    assert "# Deferred Tool Acceptance" in captured.out
    assert "Profile: `llm`" in captured.out

    assert main(["--config", str(config_path), "--profile", "llm"]) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["profile"] == "llm"
    assert report["upstream_count"] == 2
    assert captured.out.startswith('{"acceptance_scope": ')


def test_deferred_acceptance_main_reports_missing_smoke(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deferred_acceptance import main

    data = _acceptance_config(tmp_path)
    data["upstreams"]["missing-smoke"] = {
        "command": "missing-smoke",
        "enabled": True,
        "mode": "shared",
        "profiles": ["llm"],
    }
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    assert main(["--config", str(config_path), "--profile", "llm"]) == 1
    captured = capsys.readouterr()
    assert captured.err == "llm missing smoke probes: missing-smoke\n"


def test_deferred_acceptance_main_writes_stable_sorted_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.deferred_acceptance as deferred_acceptance

    monkeypatch.setattr(deferred_acceptance.BrokerConfig, "from_file", lambda _path: object())
    monkeypatch.setattr(
        deferred_acceptance,
        "build_deferred_acceptance_plan",
        lambda _config, _profile: {"z": 1, "external_llm_required": True, "a": 2},
    )

    assert deferred_acceptance.main(["--config", "/tmp/broker.yaml"]) == 0
    assert capsys.readouterr().out == '{"a": 2, "external_llm_required": true, "z": 1}\n'


def test_deferred_acceptance_parse_args_defaults_and_guards(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deferred_acceptance import _parse_args

    args = _parse_args(["--config", "/tmp/broker.yaml"])
    assert args.config == "/tmp/broker.yaml"
    assert args.profile == "codex"
    assert args.format == "json"

    explicit_json = _parse_args(["--config", "/tmp/broker.yaml", "--format", "json"])
    assert explicit_json.format == "json"

    with pytest.raises(SystemExit) as missing_config:
        _parse_args([])
    captured = capsys.readouterr()
    assert missing_config.value.code == 2
    assert "the following arguments are required: --config" in captured.err

    with pytest.raises(SystemExit) as invalid_format:
        _parse_args(["--config", "/tmp/broker.yaml", "--format", "yaml"])
    captured = capsys.readouterr()
    assert invalid_format.value.code == 2
    assert "invalid choice: 'yaml'" in captured.err

    with pytest.raises(SystemExit) as help_exit:
        _parse_args(["--help"])
    captured = capsys.readouterr()
    assert help_exit.value.code == 0
    assert "\nGenerate maintainer-only deferred-tool acceptance steps\n\noptions:" in captured.out


def _acceptance_config(tmp_path: Path) -> dict:
    return {
        "runtime": {"root": str(tmp_path / "runtime")},
        "profiles": {
            "llm": {"max_tools": 80, "compact_tools_enabled": True},
            "other": {"max_tools": 80, "compact_tools_enabled": True},
        },
        "upstreams": {
            "callable": {
                "command": "callable",
                "enabled": True,
                "mode": "shared",
                "profiles": ["llm", "other"],
                "smoke": {
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {"scope": "demo"},
                },
            },
            "other-profile": {
                "command": "other-profile",
                "enabled": True,
                "mode": "shared",
                "profiles": ["other"],
                "smoke": {
                    "query": "other status",
                    "tool": "other.status",
                    "arguments": {},
                },
            },
            "search-only": {
                "command": "search-only",
                "enabled": True,
                "mode": "shared",
                "profiles": ["llm"],
                "smoke": {
                    "query": "search only",
                    "tool": "search-only.lookup",
                    "arguments": {},
                    "call": False,
                },
            },
        },
    }
