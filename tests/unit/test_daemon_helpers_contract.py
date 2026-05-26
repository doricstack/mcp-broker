from __future__ import annotations

from datetime import datetime as RealDateTime
from datetime import timezone
from pathlib import Path
import json
from typing import Any

import pytest

from mcp_broker.config import AuthProbePolicy, AuthRepairPolicy, UpstreamConfig
import mcp_broker.daemon_helpers as daemon_helpers
from mcp_broker.daemon_helpers import (
    _parse_oauth_expiry,
    _result_content_text,
    _secret_file_has_value,
    health_profile,
    merge_passive_auth_probe,
    passive_auth_probe,
    per_session_health_snapshot,
    redact_log_field,
    redact_log_value,
    result_matches_auth_repair,
    utc_timestamp,
)


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_health_profile_defaults_when_profile_param_is_missing_or_invalid() -> None:
    assert health_profile({}) == "default"
    assert health_profile({"params": None}) == "default"
    assert health_profile({"params": {"profile": 123}}) == "default"
    assert health_profile({"params": {"profile": "codex"}}) == "codex"


@pytest.mark.parametrize(
    "upstream",
    [
        UpstreamConfig(name="disabled", command="server", enabled=False, env={"TOKEN": "HOST_TOKEN"}),
        UpstreamConfig(name="disabled", command="server", mode="disabled", env={"TOKEN": "HOST_TOKEN"}),
    ],
)
def test_passive_auth_probe_reports_none_for_disabled_upstreams(upstream: UpstreamConfig) -> None:
    assert passive_auth_probe(upstream, environ={}) == {"auth_probe": "none"}


def test_passive_auth_probe_reports_present_for_request_metadata_only() -> None:
    upstream = UpstreamConfig(
        name="meta-api",
        command="server",
        request_meta={"client": "codex"},
    )

    assert passive_auth_probe(upstream, environ={}) == {"auth_probe": "credentials_present"}


def test_passive_auth_probe_reports_present_for_secret_file_only() -> None:
    class StrictSecret:
        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return "secret-value\n"

    upstream = UpstreamConfig(
        name="file-api",
        command="server",
        env_files={"TOKEN": StrictSecret()},
    )

    assert passive_auth_probe(upstream, environ={}) == {"auth_probe": "credentials_present"}


def test_passive_auth_probe_reports_none_when_no_auth_inputs_are_configured() -> None:
    upstream = UpstreamConfig(name="plain", command="server")

    assert passive_auth_probe(upstream, environ={}) == {"auth_probe": "none"}


def test_passive_auth_probe_uses_utc_clock_when_now_is_not_supplied(tmp_path: Path) -> None:
    token_file = tmp_path / "oauth.json"
    token_file.write_text(
        json.dumps(
            {
                "refresh_token": "refresh-secret",
                "refresh_token_expires_at": "2999-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("refresh_token",),
            refresh_token_expiry_field="refresh_token_expires_at",
        ),
    )

    assert passive_auth_probe(upstream, environ={}) == {"auth_probe": "credentials_present"}


def test_passive_auth_probe_reads_oauth_token_file_as_utf8() -> None:
    class StrictTokenFile:
        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return json.dumps({"refresh_token": "refresh-secret"})

    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=StrictTokenFile(),
            required_fields=("refresh_token",),
        ),
    )

    assert passive_auth_probe(upstream, environ={}) == {"auth_probe": "credentials_present"}


def test_passive_auth_probe_treats_expiry_equal_to_now_as_expired(tmp_path: Path) -> None:
    token_file = tmp_path / "oauth.json"
    token_file.write_text(
        json.dumps(
            {
                "refresh_token": "refresh-secret",
                "refresh_token_expires_at": "2026-05-25T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("refresh_token",),
            refresh_token_expiry_field="refresh_token_expires_at",
        ),
    )

    assert passive_auth_probe(
        upstream,
        environ={},
        now=RealDateTime(2026, 5, 25, tzinfo=timezone.utc),
    ) == {
        "auth_probe": "oauth_refresh_expired",
        "auth_state": "unauthenticated",
        "last_error": "expired OAuth refresh token for upstream oauth",
    }


def test_parse_oauth_expiry_rejects_non_string_non_numeric_values() -> None:
    assert _parse_oauth_expiry(object()) is None


def test_parse_oauth_expiry_parses_z_suffix_and_offsets_to_utc() -> None:
    assert _parse_oauth_expiry("2026-05-25T00:00:00Z") == RealDateTime(
        2026,
        5,
        25,
        tzinfo=timezone.utc,
    )
    assert _parse_oauth_expiry("2026-05-25T04:00:00+04:00") == RealDateTime(
        2026,
        5,
        25,
        tzinfo=timezone.utc,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", False),
        ("\n", False),
        ("\r\n", False),
        ("X", True),
        ("XX", True),
        ("   ", True),
        ("secret\n", True),
    ],
)
def test_secret_file_has_value_requires_utf8_and_treats_newline_only_as_empty(
    value: str,
    expected: bool,
) -> None:
    class StrictSecret:
        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return value

    assert _secret_file_has_value(StrictSecret()) is expected


def test_merge_passive_auth_probe_defaults_probe_name_and_preserves_runtime_fields() -> None:
    snapshot = {
        "state": "running",
        "last_error": "runtime failed",
        "auth_state": "authenticated",
    }

    assert merge_passive_auth_probe(snapshot, {}) == {
        "state": "running",
        "last_error": "runtime failed",
        "auth_state": "authenticated",
        "auth_probe": "none",
    }
    assert merge_passive_auth_probe(snapshot, {"last_error": "missing token"})[
        "last_error"
    ] == "runtime failed"
    assert merge_passive_auth_probe(snapshot, {"auth_state": "unauthenticated"})[
        "auth_state"
    ] == "authenticated"


def test_merge_passive_auth_probe_fills_empty_or_unknown_auth_fields() -> None:
    assert merge_passive_auth_probe(
        {"state": "configured", "last_error": None},
        {
            "auth_probe": "credentials_missing",
            "auth_state": "unauthenticated",
            "last_error": "missing token",
        },
    ) == {
        "state": "configured",
        "last_error": "missing token",
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
    }
    assert merge_passive_auth_probe(
        {"auth_state": "unknown"},
        {"auth_state": "unauthenticated"},
    )["auth_state"] == "unauthenticated"


class _HealthClient:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self._snapshot = snapshot

    def health_snapshot(self) -> dict[str, object]:
        return self._snapshot


def test_per_session_health_snapshot_aggregates_running_sessions_errors_and_restarts() -> None:
    snapshot = per_session_health_snapshot(
        [
            _HealthClient({"state": "configured", "restarts": 1}),
            _HealthClient({"state": "running", "last_error": "first error", "restarts": 2}),
            _HealthClient({"state": "stopped", "last_error": "second error", "restarts": "3"}),
        ]
    )

    assert snapshot == {
        "state": "running",
        "pid": None,
        "cpu_percent": None,
        "memory_mb": None,
        "restarts": 3,
        "last_error": "first error",
        "sessions": 3,
    }


def test_per_session_health_snapshot_uses_first_state_when_no_session_is_running() -> None:
    assert per_session_health_snapshot([_HealthClient({"state": "configured"})])["state"] == "configured"


def test_result_matches_auth_repair_accepts_error_prefixed_text_without_error_flag() -> None:
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_repair=AuthRepairPolicy(
            tool="setup_auth",
            trigger_errors=("Not authenticated",),
        ),
    )

    assert result_matches_auth_repair(
        upstream,
        {"content": [{"type": "text", "text": "Error: Not authenticated"}]},
    )


def test_result_content_text_joins_multiple_text_parts_with_newlines() -> None:
    assert (
        _result_content_text(
            {
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ]
            }
        )
        == "first\nsecond"
    )


def test_redact_log_field_normalizes_hyphenated_sensitive_keys() -> None:
    assert redact_log_field("api-key", "secret-value") == "[redacted]"
    assert redact_log_field("safe-key", "safe-value") == "safe-value"


def test_redact_log_value_uses_nested_dict_keys_for_redaction() -> None:
    assert redact_log_value({"api-key": "secret-value", "safe": "plain"}) == {
        "api-key": "[redacted]",
        "safe": "plain",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/tmp/private", True),
        ("~/private", True),
        ("$HOME/private", True),
        ("${HOME}/private", True),
        ("prefix/" + "Users" + "/account/private", True),
        ("Users/account/private", False),
        ("prefix/users/account/private", False),
        ("prefix/USERS/account/private", False),
    ],
)
def test_looks_like_filesystem_path_matches_only_supported_private_path_forms(
    value: str,
    expected: bool,
) -> None:
    assert daemon_helpers.looks_like_filesystem_path(value) is expected


def test_process_exists_uses_signal_zero_and_reports_live_or_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def kill(pid: int, signal: int) -> None:
        calls.append((pid, signal))

    monkeypatch.setattr(daemon_helpers.os, "kill", kill)

    assert daemon_helpers.process_exists(12345)
    assert calls == [(12345, 0)]

    def missing(_pid: int, _signal: int) -> None:
        raise ProcessLookupError()

    monkeypatch.setattr(daemon_helpers.os, "kill", missing)
    assert daemon_helpers.process_exists(12345) is False


def test_utc_timestamp_uses_utc_timezone_and_z_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []

    class FakeDateTime:
        @classmethod
        def now(cls, tz: object) -> RealDateTime:
            calls.append(tz)
            return RealDateTime(2026, 5, 25, 12, 30, 45, tzinfo=tz)

    monkeypatch.setattr(daemon_helpers, "datetime", FakeDateTime)

    assert utc_timestamp() == "2026-05-25T12:30:45Z"
    assert calls == [timezone.utc]
