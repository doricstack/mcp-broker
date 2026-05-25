from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.unit


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
    assert [upstream["upstream"] for upstream in report["upstreams"]] == ["callable", "search-only"]
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


def test_deferred_acceptance_markdown_lists_wrapper_calls(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.deferred_acceptance import build_deferred_acceptance_plan, render_markdown

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_acceptance_config(tmp_path), sort_keys=True), encoding="utf-8")

    markdown = render_markdown(build_deferred_acceptance_plan(BrokerConfig.from_file(config_path), "llm"))

    assert "# Deferred Tool Acceptance" in markdown
    assert "Profile: `llm`" in markdown
    assert "mcp__mcp_broker__.broker_search_tools" in markdown
    assert "mcp__mcp_broker__.broker_describe_tool" in markdown
    assert "mcp__mcp_broker__.broker_call_tool" in markdown
    assert "smoke.call is false" in markdown


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
    report = yaml.safe_load(captured.out)
    assert report["profile"] == "llm"
    assert report["upstream_count"] == 2


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
    assert "llm missing smoke probes: missing-smoke" in captured.err


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
