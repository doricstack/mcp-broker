from pathlib import Path

import pytest
import yaml

from mcp_broker.discovery_parity import DiscoveryParityError
from mcp_broker.profile_validation import (
    ProfileProbe,
    build_profile_validation_plan,
    run_profile_validation,
    _search_probe_payload,
)


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


class SequenceRequester:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses

    def __call__(self, *args, **kwargs) -> dict:
        return self.responses.pop(0)


def test_build_profile_validation_plan_uses_enabled_yaml_upstreams_only(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_plan_config(tmp_path), sort_keys=True), encoding="utf-8")

    plan = build_profile_validation_plan(BrokerConfig.from_file(config_path), "llm-profile")

    assert [probe.upstream_name for probe in plan.probes] == ["callable"]
    assert plan.missing_probes == ["missing"]


def test_search_probe_payload_uses_broad_limit_for_large_profiles() -> None:
    assert _search_probe_payload("example.status")["params"]["arguments"] == {
        "query": "example.status",
        "limit": 100,
    }


def test_run_profile_validation_exercises_each_configured_probe() -> None:
    report = run_profile_validation(
        socket_path=Path("/tmp/unused.sock"),
        profile="llm-profile",
        probes=[
            {
                "upstream_name": "callable",
                "query": "callable status",
                "tool": "callable.status",
                "arguments": {},
                "call": True,
            },
            {
                "upstream_name": "search-only",
                "query": "search only",
                "tool": "search-only.lookup",
                "arguments": {},
                "call": False,
            },
        ],
        missing_probes=[],
        session_id="session",
        request_fn=SequenceRequester(_success_responses()),
    )

    assert report["matches"] is True
    assert report["missing_probes"] == []
    assert report["validated_upstreams"] == ["callable", "search-only"]
    assert report["probe_results"]["callable"]["called"] is True
    assert report["probe_results"]["callable"]["call_output_bytes"] == len('{"ok": true}')
    assert "call_text" not in report["probe_results"]["callable"]
    assert report["probe_results"]["search-only"]["called"] is False
    assert report["probe_results"]["search-only"]["call_output_bytes"] == 0


def _plan_config(tmp_path: Path) -> dict:
    return {
        "runtime": {"root": str(tmp_path / "runtime")},
        "profiles": {
            "llm-profile": {"max_tools": 80, "compact_tools_enabled": True},
            "other-llm": {"max_tools": 80, "compact_tools_enabled": True},
        },
        "upstreams": {
            "callable": _upstream_config(["llm-profile", "other-llm"], "callable.status"),
            "missing": {"command": "missing", "enabled": True, "mode": "shared", "profiles": ["llm-profile"]},
            "other-profile": _upstream_config(["other-llm"], "other.status"),
            "disabled": {"command": "disabled", "enabled": False, "mode": "disabled", "profiles": ["llm-profile"]},
        },
    }


def _upstream_config(profiles: list[str], tool: str) -> dict:
    return {
        "command": tool.split(".", 1)[0],
        "enabled": True,
        "mode": "shared",
        "profiles": profiles,
        "smoke": {"query": tool, "tool": tool, "arguments": {}},
    }


def _describe_response(tool_name: str, *, schema: dict | None = None) -> dict:
    input_schema = schema or {"type": "object", "additionalProperties": False}
    return {"result": {"structuredContent": {"tool": {"name": tool_name, "inputSchema": input_schema}}}}


def _success_responses() -> list[dict]:
    return [
        {"result": {}},
        {
            "result": {
                "structuredContent": {
                    "upstreams": {
                        "callable": {"exposed": True, "state": "running"},
                        "search-only": {"exposed": True, "state": "running"},
                    }
                }
            }
        },
        {"result": {"tools": [{"name": "broker.status"}, {"name": "broker.search_tools"}]}},
        {
            "result": {
                "structuredContent": {
                    "upstreams": {
                        "callable": {"exposed": True, "state": "running"},
                        "search-only": {"exposed": True, "state": "running"},
                    }
                }
            }
        },
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        _describe_response("callable.status"),
        {"result": {"content": [{"type": "text", "text": '{"ok": true}'}]}},
        {
            "result": {
                "structuredContent": {
                    "upstreams": {
                        "callable": {"exposed": True, "state": "running"},
                        "search-only": {"exposed": True, "state": "ready"},
                    }
                }
            }
        },
        {"result": {"structuredContent": {"matches": [{"name": "search-only.lookup"}]}}},
        _describe_response("search-only.lookup"),
        {
            "result": {
                "structuredContent": {
                    "upstreams": {
                        "callable": {"exposed": True, "state": "running"},
                        "search-only": {"exposed": True, "state": "running"},
                    }
                }
            }
        },
    ]


def test_run_profile_validation_accepts_profile_probe_objects() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        {"result": {"structuredContent": {"tool": {"name": "callable.status"}}}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
    ]

    report = run_profile_validation(
        socket_path=Path("/tmp/unused.sock"),
        profile="llm-profile",
        probes=[
            ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
                call=False,
            )
        ],
        missing_probes=[],
        session_id="session",
        request_fn=SequenceRequester(responses),
    )

    assert report["validated_upstreams"] == ["callable"]
    assert report["probe_results"]["callable"]["called"] is False


def test_run_profile_validation_rejects_invalid_status_payload() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": []}}},
    ]
    with pytest.raises(DiscoveryParityError, match="broker.status returned invalid upstream map"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_status_does_not_expose_upstream() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": False, "state": "configured"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": False}}}}},
    ]
    with pytest.raises(DiscoveryParityError, match="broker.status did not expose callable"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_exposed_upstream_is_not_healthy() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "exited"}}}}},
    ]
    with pytest.raises(DiscoveryParityError, match="callable is not healthy"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_probe_leaves_upstream_unhealthy() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        _describe_response("callable.status"),
        {"result": {"content": [{"type": "text", "text": '{"ok": true}'}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "exited"}}}}},
    ]
    with pytest.raises(DiscoveryParityError, match="callable is not healthy after probe"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_status_reports_last_error_before_search() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {
            "result": {
                "structuredContent": {
                    "upstreams": {
                        "callable": {
                            "exposed": True,
                            "state": "running",
                            "last_error": "subprocess crashed",
                        }
                    }
                }
            }
        },
    ]
    with pytest.raises(DiscoveryParityError, match="last_error='subprocess crashed'"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_search_skips_probe_upstream() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {
            "result": {
                "structuredContent": {
                    "matches": [{"name": "callable", "upstream": "callable", "available": False}],
                    "skipped_upstreams": {"callable": "process exited"},
                }
            }
        },
    ]
    with pytest.raises(DiscoveryParityError, match="search skipped callable"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_search_matches_are_not_a_list() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": {"name": "callable.status"}}}},
    ]
    with pytest.raises(DiscoveryParityError, match="search returned invalid matches"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_search_marks_probe_upstream_unavailable() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {
            "result": {
                "structuredContent": {
                    "matches": [{"name": "callable", "upstream": "callable", "available": False}],
                }
            }
        },
    ]
    with pytest.raises(DiscoveryParityError, match="search marked callable unavailable"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_describe_returns_wrong_tool() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        {"result": {"structuredContent": {"tool": {"name": "callable.other"}}}},
    ]
    with pytest.raises(DiscoveryParityError, match="describe returned callable.other"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_called_probe_has_no_described_input_schema() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        {"result": {"structuredContent": {"tool": {"name": "callable.status"}}}},
    ]
    with pytest.raises(DiscoveryParityError, match="describe returned invalid inputSchema"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_validates_called_probe_arguments_against_described_schema() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        {
            "result": {
                "structuredContent": {
                    "tool": {
                        "name": "callable.status",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"code": {"type": "string"}},
                            "required": ["code"],
                            "additionalProperties": False,
                        },
                    }
                }
            }
        },
    ]
    with pytest.raises(DiscoveryParityError, match="'code' is a required property"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {"wrong_name": "value"},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_on_bad_probe_arguments() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        _describe_response("callable.status"),
    ]
    with pytest.raises(DiscoveryParityError, match="probe arguments must be a mapping"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": [],
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_on_tool_level_error() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.status"}]}}},
        _describe_response("callable.status"),
        {"result": {"isError": True, "content": [{"type": "text", "text": "Error: denied"}]}},
    ]
    with pytest.raises(DiscoveryParityError, match="probe returned upstream error"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_validation_fails_when_yaml_upstream_lacks_probe() -> None:
    with pytest.raises(DiscoveryParityError, match="missing smoke probes: missing"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[],
            missing_probes=["missing"],
            session_id="session",
            request_fn=SequenceRequester([]),
        )


def test_run_profile_validation_fails_when_search_does_not_find_probe_tool() -> None:
    responses = [
        {"result": {}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {"callable": {"exposed": True, "state": "running"}}}}},
        {"result": {"structuredContent": {"matches": [{"name": "callable.other"}]}}},
    ]
    with pytest.raises(DiscoveryParityError, match="search did not return callable.status"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[
                {
                    "upstream_name": "callable",
                    "query": "callable status",
                    "tool": "callable.status",
                    "arguments": {},
                    "call": True,
                }
            ],
            missing_probes=[],
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_profile_validation_main_reports_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.profile_validation as profile_validation

    def raise_error(_args: object) -> dict:
        raise profile_validation.DiscoveryParityError("profile failed")

    monkeypatch.setattr(profile_validation, "_run_validation", raise_error)

    result = profile_validation.main(["--config", "/tmp/broker.yaml", "--profile", "llm"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == "profile failed\n"


def test_profile_validation_stops_session_when_existing_daemon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.profile_validation as profile_validation
    from mcp_broker.config import BrokerConfig

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_plan_config(tmp_path), sort_keys=True), encoding="utf-8")
    stopped: list[tuple[Path, str, str]] = []
    broker_daemon_error = profile_validation._start_daemon_if_needed.__globals__["BrokerDaemonError"]

    class AlreadyRunningDaemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise broker_daemon_error("broker daemon already running")

    monkeypatch.setattr(profile_validation, "BrokerDaemon", AlreadyRunningDaemon)
    monkeypatch.setattr(profile_validation, "build_profile_validation_plan", lambda _config, _profile: type("Plan", (), {"probes": [], "missing_probes": []})())
    monkeypatch.setattr(
        profile_validation,
        "run_profile_validation",
        lambda **_kwargs: {"matches": True, "validated_upstreams": []},
    )
    monkeypatch.setattr(
        profile_validation,
        "_stop_smoke_session",
        lambda socket_path, profile, session_id: stopped.append((socket_path, profile, session_id)),
    )

    report = profile_validation._run_validation(
        type("Args", (), {"config": str(config_path), "profile": "llm"})()
    )

    config = BrokerConfig.from_file(config_path)
    assert report == {"matches": True, "validated_upstreams": [], "started_daemon": False}
    assert stopped[0][0] == config.runtime.socket_path
    assert stopped[0][1] == "llm"
