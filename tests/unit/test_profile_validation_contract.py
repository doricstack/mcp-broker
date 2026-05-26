from pathlib import Path

import pytest
import yaml

from mcp_broker.discovery_parity import DiscoveryParityError
from mcp_broker.profile_validation import (
    ProfileProbe,
    build_profile_validation_plan,
    run_profile_validation,
    _call_probe_if_enabled,
    _load_facade_state,
    _load_upstream_status,
    _require_exposed_upstream,
    _run_single_probe,
    _normalize_probe,
    _parse_args,
    _raise_on_unavailable_probe_catalog,
    _raise_on_unhealthy_exposed_upstreams,
    _search_and_describe_probe,
    _search_probe_payload,
    _upstreams_from_status,
)


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


class SequenceRequester:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses

    def __call__(self, *args, **kwargs) -> dict:
        return self.responses.pop(0)


class RecordingSequenceRequester(SequenceRequester):
    def __init__(self, responses: list[dict]) -> None:
        super().__init__(responses)
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args, **kwargs) -> dict:
        self.calls.append((args, kwargs))
        return super().__call__(*args, **kwargs)


def test_build_profile_validation_plan_uses_enabled_yaml_upstreams_only(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_plan_config(tmp_path), sort_keys=True), encoding="utf-8")

    plan = build_profile_validation_plan(BrokerConfig.from_file(config_path), "llm-profile")

    assert [probe.upstream_name for probe in plan.probes] == ["callable"]
    assert plan.missing_probes == ["missing", "missing-later"]


def test_search_probe_payload_uses_broad_limit_for_large_profiles() -> None:
    payload = _search_probe_payload("example.status")

    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "broker.search_tools"
    assert payload["method"] == "tools/call"
    assert payload["params"]["name"] == "broker.search_tools"
    assert payload["params"]["arguments"] == {
        "query": "example.status",
        "limit": 100,
    }


def test_parse_args_defaults_to_generic_codex_profile() -> None:
    args = _parse_args(["--config", "/tmp/example.yaml"])

    assert args.config == "/tmp/example.yaml"
    assert args.profile == "codex"


def test_parse_args_accepts_explicit_generic_profile() -> None:
    args = _parse_args(["--config", "/tmp/example.yaml", "--profile", "llm"])

    assert args.config == "/tmp/example.yaml"
    assert args.profile == "llm"


def test_parse_args_requires_config(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse_args([])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "the following arguments are required: --config" in captured.err


def test_parse_args_help_exposes_profile_validation_description(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "\nValidate all enabled profile upstreams with YAML smoke probes\n" in captured.out
    assert "XXValidate" not in captured.out


def test_normalize_probe_preserves_object_identity() -> None:
    probe = ProfileProbe(
        upstream_name="example",
        query="example status",
        tool="example.status",
        arguments={},
        call=False,
    )

    assert _normalize_probe(probe) is probe


def test_normalize_probe_defaults_optional_fields() -> None:
    probe = _normalize_probe(
        {
            "upstream_name": "example",
            "query": "example status",
            "tool": "example.status",
        }
    )

    assert probe == ProfileProbe(
        upstream_name="example",
        query="example status",
        tool="example.status",
        arguments={},
        call=True,
    )


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
    assert set(report) == {
        "matches",
        "profile",
        "advertised_tools",
        "visible_upstreams",
        "validated_upstreams",
        "missing_probes",
        "probe_results",
    }
    assert report["profile"] == "llm-profile"
    assert report["advertised_tools"] == ["broker.search_tools", "broker.status"]
    assert report["visible_upstreams"] == ["callable", "search-only"]
    assert report["missing_probes"] == []
    assert report["validated_upstreams"] == ["callable", "search-only"]
    assert report["probe_results"]["callable"]["called"] is True
    assert report["probe_results"]["callable"]["call_output_bytes"] == len('{"ok": true}')
    assert "call_text" not in report["probe_results"]["callable"]
    assert report["probe_results"]["search-only"]["called"] is False
    assert report["probe_results"]["search-only"]["call_output_bytes"] == 0


def test_run_single_probe_forwards_context_and_returns_probe_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.profile_validation as profile_validation

    socket_path = Path("/tmp/profile-validation.sock")
    upstreams = {"callable": {"exposed": True, "state": "reachable"}}
    final_upstreams = {"callable": {"exposed": True, "state": "running"}}
    probe = ProfileProbe(
        upstream_name="callable",
        query="callable status",
        tool="callable.status",
        arguments={"check": True},
    )
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def require(
        profile: str,
        snapshot: dict[str, object],
        upstream_name: str,
        **kwargs: object,
    ) -> dict[str, object]:
        calls.append(("require", (profile, snapshot, upstream_name), kwargs))
        return {"state": "reachable"}

    def search(**kwargs: object) -> tuple[list[str], str, dict[str, object]]:
        calls.append(("search", (), kwargs))
        return ["callable.status"], "callable.status", {"type": "object"}

    def call(**kwargs: object) -> dict[str, object]:
        calls.append(("call", (), kwargs))
        return {"called": True, "call_content_items": 1, "call_output_bytes": 2}

    def load_status(*args: object) -> dict[str, object]:
        calls.append(("load_status", args, {}))
        return final_upstreams

    monkeypatch.setattr(profile_validation, "_require_exposed_upstream", require)
    monkeypatch.setattr(profile_validation, "_search_and_describe_probe", search)
    monkeypatch.setattr(profile_validation, "_call_probe_if_enabled", call)
    monkeypatch.setattr(profile_validation, "_load_upstream_status", load_status)

    result = _run_single_probe(
        socket_path=socket_path,
        profile="llm-profile",
        session_id="session",
        upstreams=upstreams,
        probe=probe,
        request_fn=lambda *_args, **_kwargs: {},
    )

    assert result == {
        "state": "reachable",
        "search_matches": ["callable.status"],
        "described_tool": "callable.status",
        "called": True,
        "call_content_items": 1,
        "call_output_bytes": 2,
    }
    assert calls[0] == (
        "require",
        ("llm-profile", upstreams, "callable"),
        {"context": "", "require_active": False},
    )
    assert calls[1] == (
        "search",
        (),
        {
            "socket_path": socket_path,
            "profile": "llm-profile",
            "session_id": "session",
            "probe": probe,
            "request_fn": calls[1][2]["request_fn"],
        },
    )
    assert calls[2] == (
        "call",
        (),
        {
            "socket_path": socket_path,
            "profile": "llm-profile",
            "session_id": "session",
            "probe": probe,
            "input_schema": {"type": "object"},
            "request_fn": calls[2][2]["request_fn"],
        },
    )
    assert calls[3] == ("load_status", (socket_path, "llm-profile", "session", calls[3][1][3]), {})
    assert calls[4] == (
        "require",
        ("llm-profile", final_upstreams, "callable"),
        {"context": "after probe", "require_active": True},
    )


def test_run_profile_validation_sends_expected_client_requests() -> None:
    socket_path = Path("/tmp/profile-validation.sock")
    requester = RecordingSequenceRequester(_success_responses())

    report = run_profile_validation(
        socket_path=socket_path,
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
        request_fn=requester,
    )

    assert report["validated_upstreams"] == ["callable", "search-only"]
    assert [call_args[:3] for call_args, _kwargs in requester.calls] == [
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
        (socket_path, "llm-profile", "session"),
    ]
    payloads = [call_args[3] for call_args, _kwargs in requester.calls]
    assert [payload["method"] for payload in payloads] == [
        "initialize",
        "tools/call",
        "tools/list",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
        "tools/call",
    ]
    assert payloads[1]["params"]["name"] == "broker.status"
    assert payloads[4]["params"]["arguments"] == {"query": "callable status", "limit": 100}
    assert payloads[5]["params"]["arguments"] == {"name": "callable.status"}
    assert payloads[6]["params"]["arguments"] == {
        "name": "callable.status",
        "arguments": {},
    }
    assert payloads[8]["params"]["arguments"] == {"query": "search only", "limit": 100}
    assert payloads[9]["params"]["arguments"] == {"name": "search-only.lookup"}


def test_run_profile_validation_reports_missing_probes_in_sorted_order() -> None:
    with pytest.raises(DiscoveryParityError, match="llm-profile missing smoke probes: alpha, zebra"):
        run_profile_validation(
            socket_path=Path("/tmp/unused.sock"),
            profile="llm-profile",
            probes=[],
            missing_probes=["zebra", "alpha"],
            session_id="session",
            request_fn=SequenceRequester([]),
        )


def test_run_profile_validation_ignores_hidden_and_malformed_upstreams_in_visibility() -> None:
    responses = [
        {"result": {}},
        {
            "result": {
                "structuredContent": {
                    "upstreams": {
                        "callable": {"exposed": True, "state": "running"},
                        "hidden": {"exposed": False, "state": "running"},
                        "malformed": "not a snapshot",
                    }
                }
            }
        },
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {
            "result": {
                "structuredContent": {
                    "upstreams": {
                        "callable": {"exposed": True, "state": "running"},
                        "hidden": {"exposed": False, "state": "running"},
                        "malformed": "not a snapshot",
                    }
                }
            }
        },
    ]

    report = run_profile_validation(
        socket_path=Path("/tmp/unused.sock"),
        profile="llm-profile",
        probes=[],
        missing_probes=[],
        session_id="session",
        request_fn=SequenceRequester(responses),
    )

    assert report["visible_upstreams"] == ["callable"]


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
            "missing-later": {
                "command": "missing-later",
                "enabled": True,
                "mode": "shared",
                "profiles": ["llm-profile"],
            },
            "other-profile": _upstream_config(["other-llm"], "other.status"),
            "disabled": {"command": "disabled", "enabled": False, "mode": "disabled", "profiles": ["llm-profile"]},
            "disabled-shared": {
                **_upstream_config(["llm-profile"], "disabled-shared.status"),
                "enabled": False,
                "mode": "shared",
            },
            "mode-disabled": {
                **_upstream_config(["llm-profile"], "mode-disabled.status"),
                "enabled": True,
                "mode": "disabled",
            },
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


def test_call_probe_if_enabled_counts_multiple_content_items() -> None:
    requester = RecordingSequenceRequester(
        [
            {
                "result": {
                    "content": [
                        {"type": "text", "text": "first"},
                        {"type": "text", "text": "second"},
                    ]
                }
            }
        ]
    )

    result = _call_probe_if_enabled(
        socket_path=Path("/tmp/profile-validation.sock"),
        profile="llm-profile",
        session_id="session",
        probe=ProfileProbe(
            upstream_name="callable",
            query="callable status",
            tool="callable.status",
            arguments={"enabled": True},
        ),
        input_schema={
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}},
            "required": ["enabled"],
            "additionalProperties": False,
        },
        request_fn=requester,
    )

    assert result == {"called": True, "call_content_items": 2, "call_output_bytes": 11}
    payload = requester.calls[0][0][3]
    assert payload["params"]["arguments"] == {
        "name": "callable.status",
        "arguments": {"enabled": True},
    }


def test_call_probe_if_enabled_passes_profile_to_schema_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.profile_validation as profile_validation

    seen: list[tuple[str, ProfileProbe, dict[str, object] | None, dict[str, object]]] = []
    probe = ProfileProbe(
        upstream_name="callable",
        query="callable status",
        tool="callable.status",
        arguments={},
    )

    def validate(
        profile: str,
        validated_probe: ProfileProbe,
        input_schema: dict[str, object] | None,
        arguments: dict[str, object],
    ) -> None:
        seen.append((profile, validated_probe, input_schema, arguments))

    monkeypatch.setattr(profile_validation, "_validate_probe_arguments", validate)

    result = _call_probe_if_enabled(
        socket_path=Path("/tmp/profile-validation.sock"),
        profile="llm-profile",
        session_id="session",
        probe=probe,
        input_schema={"type": "object"},
        request_fn=SequenceRequester([{"result": {}}]),
    )

    assert result == {"called": True, "call_content_items": 0, "call_output_bytes": 0}
    assert seen == [("llm-profile", probe, {"type": "object"}, {})]


def test_call_probe_if_enabled_handles_missing_content_as_empty_result() -> None:
    result = _call_probe_if_enabled(
        socket_path=Path("/tmp/profile-validation.sock"),
        profile="llm-profile",
        session_id="session",
        probe=ProfileProbe(
            upstream_name="callable",
            query="callable status",
            tool="callable.status",
            arguments={},
        ),
        input_schema={"type": "object", "additionalProperties": False},
        request_fn=SequenceRequester([{"result": {}}]),
    )

    assert result == {"called": True, "call_content_items": 0, "call_output_bytes": 0}


def test_call_probe_if_enabled_reports_empty_error_text_when_error_has_no_content() -> None:
    with pytest.raises(DiscoveryParityError, match=r"probe returned upstream error: $"):
        _call_probe_if_enabled(
            socket_path=Path("/tmp/profile-validation.sock"),
            profile="llm-profile",
            session_id="session",
            probe=ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
            ),
            input_schema={"type": "object", "additionalProperties": False},
            request_fn=SequenceRequester([{"result": {"isError": True}}]),
        )


def test_call_probe_if_enabled_skips_search_only_probe_without_schema() -> None:
    requester = RecordingSequenceRequester([])

    result = _call_probe_if_enabled(
        socket_path=Path("/tmp/profile-validation.sock"),
        profile="llm-profile",
        session_id="session",
        probe=ProfileProbe(
            upstream_name="search-only",
            query="search only",
            tool="search-only.lookup",
            arguments={},
            call=False,
        ),
        input_schema=None,
        request_fn=requester,
    )

    assert result == {"called": False, "call_content_items": 0, "call_output_bytes": 0}
    assert requester.calls == []


def test_call_probe_if_enabled_rejects_upstream_error_flag() -> None:
    requester = RecordingSequenceRequester(
        [{"result": {"isError": True, "content": [{"type": "text", "text": "failed"}]}}]
    )

    with pytest.raises(DiscoveryParityError, match="probe returned upstream error: failed"):
        _call_probe_if_enabled(
            socket_path=Path("/tmp/profile-validation.sock"),
            profile="llm-profile",
            session_id="session",
            probe=ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
            ),
            input_schema={"type": "object", "additionalProperties": False},
            request_fn=requester,
        )


def test_call_probe_if_enabled_rejects_error_text_prefix() -> None:
    requester = RecordingSequenceRequester(
        [{"result": {"content": [{"type": "text", "text": "Error: unavailable"}]}}]
    )

    with pytest.raises(DiscoveryParityError, match="probe returned upstream error: Error: unavailable"):
        _call_probe_if_enabled(
            socket_path=Path("/tmp/profile-validation.sock"),
            profile="llm-profile",
            session_id="session",
            probe=ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
            ),
            input_schema={"type": "object", "additionalProperties": False},
            request_fn=requester,
        )


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


@pytest.mark.parametrize("bad_state", ["exited", "failed", "backoff"])
def test_require_exposed_upstream_rejects_terminal_states(bad_state: str) -> None:
    with pytest.raises(DiscoveryParityError) as exc_info:
        _require_exposed_upstream(
            "llm-profile",
            {"callable": {"exposed": True, "state": bad_state}},
            "callable",
            context="",
            require_active=True,
        )
    assert str(exc_info.value) == f"llm-profile upstream callable is not healthy: state='{bad_state}'"


@pytest.mark.parametrize("bad_state", ["exited", "failed", "backoff"])
def test_require_exposed_upstream_rejects_terminal_states_before_probe(bad_state: str) -> None:
    with pytest.raises(
        DiscoveryParityError,
        match=f"llm-profile upstream callable is not healthy: state='{bad_state}'",
    ):
        _require_exposed_upstream(
            "llm-profile",
            {"callable": {"exposed": True, "state": bad_state}},
            "callable",
            context="",
            require_active=False,
        )


def test_require_exposed_upstream_allows_configured_state_before_probe_only() -> None:
    snapshot = {"exposed": True, "state": "configured"}

    assert (
        _require_exposed_upstream(
            "llm-profile",
            {"callable": snapshot},
            "callable",
            context="",
            require_active=False,
        )
        is snapshot
    )
    with pytest.raises(DiscoveryParityError, match="state='configured'"):
        _require_exposed_upstream(
            "llm-profile",
            {"callable": snapshot},
            "callable",
            context="",
            require_active=True,
        )


def test_require_exposed_upstream_default_requires_active_state() -> None:
    with pytest.raises(DiscoveryParityError) as exc_info:
        _require_exposed_upstream(
            "llm-profile",
            {"callable": {"exposed": True, "state": "configured"}},
            "callable",
            context="",
            require_active=True,
        )

    assert str(exc_info.value) == "llm-profile upstream callable is not healthy: state='configured'"


def test_require_exposed_upstream_rejects_last_error_with_context() -> None:
    with pytest.raises(DiscoveryParityError, match="after probe: last_error='boom'"):
        _require_exposed_upstream(
            "llm-profile",
            {"callable": {"exposed": True, "state": "running", "last_error": "boom"}},
            "callable",
            context="after probe",
            require_active=True,
        )


def test_require_exposed_upstream_rejects_last_error_without_context() -> None:
    with pytest.raises(
        DiscoveryParityError,
        match="llm-profile upstream callable is not healthy: last_error='boom'",
    ):
        _require_exposed_upstream(
            "llm-profile",
            {"callable": {"exposed": True, "state": "running", "last_error": "boom"}},
            "callable",
            context="",
            require_active=True,
        )


def test_raise_on_unhealthy_exposed_upstreams_ignores_hidden_upstreams() -> None:
    _raise_on_unhealthy_exposed_upstreams(
        "llm-profile",
        {
            "hidden": {"exposed": False, "state": "failed", "last_error": "hidden"},
            "malformed": "not a snapshot",
        },
    )


def test_raise_on_unhealthy_exposed_upstreams_keeps_scanning_after_hidden_upstream() -> None:
    with pytest.raises(DiscoveryParityError, match="state='failed'"):
        _raise_on_unhealthy_exposed_upstreams(
            "llm-profile",
            {
                "hidden": {"exposed": False, "state": "running"},
                "callable": {"exposed": True, "state": "failed"},
            },
        )


def test_raise_on_unhealthy_exposed_upstreams_rejects_last_error() -> None:
    with pytest.raises(DiscoveryParityError, match="state='running'"):
        _raise_on_unhealthy_exposed_upstreams(
            "llm-profile",
            {"callable": {"exposed": True, "state": "running", "last_error": "boom"}},
        )


@pytest.mark.parametrize("bad_state", ["exited", "failed", "backoff"])
def test_raise_on_unhealthy_exposed_upstreams_rejects_terminal_state(bad_state: str) -> None:
    with pytest.raises(
        DiscoveryParityError,
        match=f"llm-profile upstream callable is not healthy before probe: state='{bad_state}'",
    ):
        _raise_on_unhealthy_exposed_upstreams(
            "llm-profile",
            {"callable": {"exposed": True, "state": bad_state}},
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


def test_upstreams_from_status_treats_missing_upstream_map_as_empty() -> None:
    assert _upstreams_from_status("llm-profile", {"result": {"structuredContent": {}}}) == {}


def test_load_upstream_status_uses_profile_in_invalid_status_error() -> None:
    with pytest.raises(DiscoveryParityError, match="llm-profile broker.status returned invalid upstream map"):
        _load_upstream_status(
            Path("/tmp/profile-validation.sock"),
            "llm-profile",
            "session",
            SequenceRequester([{"result": {"structuredContent": {"upstreams": []}}}]),
        )


def test_load_facade_state_uses_profile_for_initial_and_final_status_errors() -> None:
    with pytest.raises(DiscoveryParityError, match="llm-profile broker.status returned invalid upstream map"):
        _load_facade_state(
            Path("/tmp/profile-validation.sock"),
            "llm-profile",
            "session",
            SequenceRequester(
                [
                    {"result": {}},
                    {"result": {"structuredContent": {"upstreams": []}}},
                ]
            ),
        )

    with pytest.raises(DiscoveryParityError, match="llm-profile broker.status returned invalid upstream map"):
        _load_facade_state(
            Path("/tmp/profile-validation.sock"),
            "llm-profile",
            "session",
            SequenceRequester(
                [
                    {"result": {}},
                    {"result": {"structuredContent": {"upstreams": {}}}},
                    {"result": {"tools": []}},
                    {"result": {"structuredContent": {"upstreams": []}}},
                ]
            ),
        )


def test_load_facade_state_uses_profile_for_initial_unhealthy_error() -> None:
    with pytest.raises(
        DiscoveryParityError,
        match="llm-profile upstream callable is not healthy before probe: state='failed'",
    ):
        _load_facade_state(
            Path("/tmp/profile-validation.sock"),
            "llm-profile",
            "session",
            SequenceRequester(
                [
                    {"result": {}},
                    {
                        "result": {
                            "structuredContent": {
                                "upstreams": {"callable": {"exposed": True, "state": "failed"}}
                            }
                        }
                    },
                ]
            ),
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


def test_raise_on_unavailable_probe_catalog_ignores_other_upstream_unavailable_match() -> None:
    _raise_on_unavailable_probe_catalog(
        "llm-profile",
        {
            "matches": [
                {"name": "other.status", "upstream": "other", "available": False},
                {"name": "callable.status", "upstream": "callable", "available": True},
            ]
        },
        ProfileProbe(
            upstream_name="callable",
            query="callable status",
            tool="callable.status",
            arguments={},
        ),
    )


def test_raise_on_unavailable_probe_catalog_reports_matching_unavailable_tool() -> None:
    with pytest.raises(DiscoveryParityError, match="llm-profile search marked callable unavailable"):
        _raise_on_unavailable_probe_catalog(
            "llm-profile",
            {"matches": [{"name": "callable.status", "upstream": "callable", "available": False}]},
            ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
            ),
        )


def test_raise_on_unavailable_probe_catalog_rejects_malformed_skipped_upstreams() -> None:
    with pytest.raises(DiscoveryParityError, match="llm-profile search returned invalid skipped_upstreams"):
        _raise_on_unavailable_probe_catalog(
            "llm-profile",
            {"matches": [], "skipped_upstreams": ["callable"]},
            ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
            ),
        )


def test_search_and_describe_probe_reports_profile_when_catalog_skips_upstream() -> None:
    with pytest.raises(DiscoveryParityError, match="llm-profile search skipped callable: process exited"):
        _search_and_describe_probe(
            socket_path=Path("/tmp/profile-validation.sock"),
            profile="llm-profile",
            session_id="session",
            probe=ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
            ),
            request_fn=SequenceRequester(
                [
                    {
                        "result": {
                            "structuredContent": {
                                "matches": [],
                                "skipped_upstreams": {"callable": "process exited"},
                            }
                        }
                    }
                ]
            ),
        )


def test_search_and_describe_probe_rejects_missing_matches() -> None:
    with pytest.raises(DiscoveryParityError, match="search did not return callable.status"):
        _search_and_describe_probe(
            socket_path=Path("/tmp/profile-validation.sock"),
            profile="llm-profile",
            session_id="session",
            probe=ProfileProbe(
                upstream_name="callable",
                query="callable status",
                tool="callable.status",
                arguments={},
            ),
            request_fn=SequenceRequester([{"result": {"structuredContent": {}}}]),
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


def test_profile_validation_main_parses_args_and_writes_sorted_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.profile_validation as profile_validation

    seen_args: list[object] = []

    def run_validation(args: object) -> dict[str, object]:
        seen_args.append(args)
        return {"profile": args.profile, "matches": True}

    monkeypatch.setattr(profile_validation, "_run_validation", run_validation)

    result = profile_validation.main(["--config", "/tmp/broker.yaml", "--profile", "llm"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == '{"matches": true, "profile": "llm"}\n'
    assert captured.err == ""
    assert seen_args[0].config == "/tmp/broker.yaml"
    assert seen_args[0].profile == "llm"


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


def test_run_validation_wires_config_plan_session_and_existing_daemon_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.profile_validation as profile_validation
    from mcp_broker.config import BrokerConfig

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_plan_config(tmp_path), sort_keys=True), encoding="utf-8")
    config = BrokerConfig.from_file(config_path)
    probe = ProfileProbe(
        upstream_name="callable",
        query="callable status",
        tool="callable.status",
        arguments={},
    )
    missing_probes = ["missing"]
    daemon_kwargs: list[dict[str, object]] = []
    validation_kwargs: list[dict[str, object]] = []
    stopped: list[tuple[Path, str, str]] = []

    class RecordingDaemon:
        def __init__(self, **kwargs: object) -> None:
            daemon_kwargs.append(kwargs)

    def build_plan(plan_config: BrokerConfig, profile: str) -> object:
        assert plan_config.runtime.root == config.runtime.root
        assert profile == "llm"
        return type("Plan", (), {"probes": (probe,), "missing_probes": missing_probes})()

    def validate(**kwargs: object) -> dict[str, object]:
        validation_kwargs.append(kwargs)
        assert kwargs["socket_path"] == config.runtime.socket_path
        assert kwargs["profile"] == "llm"
        assert kwargs["probes"] == (probe,)
        assert kwargs["missing_probes"] is missing_probes
        assert isinstance(kwargs["session_id"], str)
        assert str(kwargs["session_id"]).startswith("profile-validation-llm-")
        return {"matches": True, "validated_upstreams": ["callable"]}

    monkeypatch.setattr(profile_validation, "BrokerDaemon", RecordingDaemon)
    monkeypatch.setattr(profile_validation, "build_profile_validation_plan", build_plan)
    monkeypatch.setattr(profile_validation, "_start_daemon_if_needed", lambda daemon: False)
    monkeypatch.setattr(profile_validation, "run_profile_validation", validate)
    monkeypatch.setattr(
        profile_validation,
        "_stop_smoke_session",
        lambda socket_path, profile, session_id: stopped.append((socket_path, profile, session_id)),
    )

    report = profile_validation._run_validation(
        type("Args", (), {"config": str(config_path), "profile": "llm"})()
    )

    assert report == {
        "matches": True,
        "validated_upstreams": ["callable"],
        "started_daemon": False,
    }
    assert len(daemon_kwargs) == 1
    assert daemon_kwargs[0]["runtime_root"] == config.runtime.root
    assert daemon_kwargs[0]["socket_path"] == config.runtime.socket_path
    assert isinstance(daemon_kwargs[0]["broker_config"], BrokerConfig)
    assert daemon_kwargs[0]["broker_config"].runtime.root == config.runtime.root
    assert stopped == [
        (config.runtime.socket_path, "llm", validation_kwargs[0]["session_id"]),
    ]


def test_run_validation_stops_started_daemon_with_broker_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.profile_validation as profile_validation
    from mcp_broker.config import BrokerConfig

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump(_plan_config(tmp_path), sort_keys=True), encoding="utf-8")
    config = BrokerConfig.from_file(config_path)
    events: list[tuple[str, object]] = []

    class RecordingDaemon:
        def __init__(self, **kwargs: object) -> None:
            events.append(("init", kwargs))

        def join(self, timeout: int) -> None:
            events.append(("join", timeout))

        def stop(self) -> None:
            events.append(("stop", None))

    monkeypatch.setattr(profile_validation, "BrokerDaemon", RecordingDaemon)
    monkeypatch.setattr(
        profile_validation,
        "build_profile_validation_plan",
        lambda _config, _profile: type("Plan", (), {"probes": (), "missing_probes": []})(),
    )
    monkeypatch.setattr(profile_validation, "_start_daemon_if_needed", lambda daemon: True)
    monkeypatch.setattr(
        profile_validation,
        "run_profile_validation",
        lambda **_kwargs: {"matches": True, "validated_upstreams": []},
    )
    monkeypatch.setattr(
        profile_validation,
        "_request_through_client",
        lambda **kwargs: events.append(("request", kwargs)),
    )

    report = profile_validation._run_validation(
        type("Args", (), {"config": str(config_path), "profile": "llm"})()
    )

    assert report == {"matches": True, "validated_upstreams": [], "started_daemon": True}
    assert events[0] == (
        "init",
        {
            "runtime_root": config.runtime.root,
            "socket_path": config.runtime.socket_path,
            "broker_config": BrokerConfig.from_file(config_path),
        },
    )
    assert events[1] == (
        "request",
        {
            "socket_path": config.runtime.socket_path,
            "profile": "llm",
            "session_id": "profile-validation-stop",
            "payload": {"jsonrpc": "2.0", "id": "stop", "method": "broker/stop"},
        },
    )
    assert events[2:] == [("join", 5), ("stop", None)]
