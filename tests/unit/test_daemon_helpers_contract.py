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


# --- survivors in result_matches_auth_repair ---------------------------------
# The guard is `result.get("isError") is not True and not text.startswith("Error:")`.
# Both halves, the identity comparison, and the trigger scan each need a case that
# fails when they change.


def _auth_repair_upstream(*triggers: str) -> UpstreamConfig:
    return UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_repair=AuthRepairPolicy(
            tool="setup_auth",
            trigger_errors=triggers or ("Not authenticated",),
        ),
    )


def test_result_matches_auth_repair_accepts_is_error_flag_without_error_prefix() -> None:
    """isError True alone is enough; the text need not start with Error:."""
    assert result_matches_auth_repair(
        _auth_repair_upstream(),
        {"isError": True, "content": [{"type": "text", "text": "Not authenticated"}]},
    )


def test_result_matches_auth_repair_rejects_plain_text_with_no_error_signal() -> None:
    """Neither isError nor an Error: prefix means this is not a failure to repair,
    even though the trigger string is present."""
    assert not result_matches_auth_repair(
        _auth_repair_upstream(),
        {"content": [{"type": "text", "text": "Not authenticated"}]},
    )


def test_result_matches_auth_repair_requires_isError_to_be_exactly_true() -> None:
    """The check is `is not True`, an identity test. A truthy non-True value such as
    1 must not satisfy it, so this result falls back to the Error: prefix and fails."""
    assert not result_matches_auth_repair(
        _auth_repair_upstream(),
        {"isError": 1, "content": [{"type": "text", "text": "Not authenticated"}]},
    )


def test_result_matches_auth_repair_rejects_error_whose_text_matches_no_trigger() -> None:
    """A real error that is not one of the configured triggers is not repairable."""
    assert not result_matches_auth_repair(
        _auth_repair_upstream("Not authenticated"),
        {"isError": True, "content": [{"type": "text", "text": "Quota exceeded"}]},
    )


def test_result_matches_auth_repair_scans_every_configured_trigger() -> None:
    """The scan is over all triggers, not just the first."""
    upstream = _auth_repair_upstream("Not authenticated", "Token expired")
    assert result_matches_auth_repair(
        upstream,
        {"isError": True, "content": [{"type": "text", "text": "Token expired"}]},
    )


def test_result_matches_auth_repair_matches_a_trigger_anywhere_in_the_text() -> None:
    """Containment, not a prefix match."""
    assert result_matches_auth_repair(
        _auth_repair_upstream("Not authenticated"),
        {
            "isError": True,
            "content": [{"type": "text", "text": "upstream said: Not authenticated (401)"}],
        },
    )


def test_result_matches_auth_repair_rejects_empty_text_even_when_flagged_an_error() -> None:
    assert not result_matches_auth_repair(
        _auth_repair_upstream(),
        {"isError": True, "content": []},
    )


def test_result_matches_auth_repair_rejects_upstream_without_a_repair_policy() -> None:
    assert not result_matches_auth_repair(
        UpstreamConfig(name="plain", command="plain"),
        {"isError": True, "content": [{"type": "text", "text": "Not authenticated"}]},
    )


def test_result_matches_auth_repair_rejects_when_no_trigger_is_configured() -> None:
    """An empty trigger list matches nothing, rather than everything."""
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_repair=AuthRepairPolicy(tool="setup_auth", trigger_errors=()),
    )
    assert not result_matches_auth_repair(
        upstream,
        {"isError": True, "content": [{"type": "text", "text": "Not authenticated"}]},
    )


# --- survivors in configured_upstream_health ---------------------------------
# The state is disabled when `not upstream.enabled or upstream.mode == "disabled"`.
# Each half has to decide the answer on its own.


def test_configured_upstream_health_reports_configured_for_an_enabled_upstream() -> None:
    snapshot = daemon_helpers.configured_upstream_health(
        UpstreamConfig(name="live", command="live", enabled=True, mode="shared")
    )
    assert snapshot["state"] == "configured"
    assert snapshot["pid"] is None
    assert snapshot["restarts"] == 0
    assert snapshot["last_error"] is None


def test_configured_upstream_health_reports_disabled_when_the_flag_is_off() -> None:
    """enabled=False decides it even though the mode is a running one."""
    snapshot = daemon_helpers.configured_upstream_health(
        UpstreamConfig(name="off", command="off", enabled=False, mode="shared")
    )
    assert snapshot["state"] == "disabled"


def test_configured_upstream_health_reports_disabled_when_the_mode_is_disabled() -> None:
    """mode='disabled' decides it even though the enabled flag is on."""
    snapshot = daemon_helpers.configured_upstream_health(
        UpstreamConfig(name="off", command="off", enabled=True, mode="disabled")
    )
    assert snapshot["state"] == "disabled"


def test_configured_upstream_health_always_reports_the_same_idle_fields() -> None:
    """The non-state fields are fixed, so a mutant changing one is observable."""
    snapshot = daemon_helpers.configured_upstream_health(
        UpstreamConfig(name="live", command="live")
    )
    assert snapshot["cpu_percent"] is None
    assert snapshot["memory_mb"] is None
    assert set(snapshot) == {
        "state",
        "pid",
        "cpu_percent",
        "memory_mb",
        "restarts",
        "last_error",
    }


# --- survivor in stdio_client_name -------------------------------------------


def test_stdio_client_name_joins_a_tuple_key_in_order() -> None:
    """Order and separator both matter: owner first, then call id."""
    assert daemon_helpers.stdio_client_name(("owner", "call-1")) == "owner:call-1"


def test_stdio_client_name_passes_a_plain_string_key_through() -> None:
    assert daemon_helpers.stdio_client_name("shared") == "shared"


# --- survivor in redact_log_value --------------------------------------------


def test_redact_log_value_redacts_a_url_before_considering_it_a_path() -> None:
    assert redact_log_value("https://example.test/a/b") == "[redacted:url]"


def test_redact_log_value_converts_a_tuple_to_a_list_and_redacts_inside_it() -> None:
    """Tuples come back as lists, and their members are redacted too."""
    assert redact_log_value(("plain", "https://example.test")) == [
        "plain",
        "[redacted:url]",
    ]


def test_redact_log_value_leaves_an_ordinary_string_alone() -> None:
    assert redact_log_value("hello") == "hello"


def test_redact_log_value_recurses_through_nested_containers() -> None:
    assert redact_log_value([{"u": "https://example.test"}]) == [{"u": "[redacted:url]"}]


# --- survivors in the OAuth probe paths --------------------------------------


def _oauth_upstream(
    token_file: Path,
    *,
    required: tuple[str, ...] = ("access_token",),
    expiry_field: str | None = None,
) -> UpstreamConfig:
    return UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            # A Path, not a string: _read_secret_text reads through a .read_text
            # protocol, so a plain string path resolves to "missing" and every
            # assertion below would pass for the wrong reason.
            type="oauth_token_file",
            token_file=token_file,
            required_fields=required,
            refresh_token_expiry_field=expiry_field,
        ),
    )


def test_passive_auth_probe_treats_a_newline_only_token_file_as_missing(
    tmp_path: Path,
) -> None:
    """The guard asks whether any character is not a carriage return or newline.
    A file of pure line endings carries no token."""
    token = tmp_path / "token.json"
    token.write_text("\r\n\r\n", encoding="utf-8")

    assert passive_auth_probe(_oauth_upstream(token), environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing OAuth token file for upstream oauth",
    }


def test_passive_auth_probe_reads_a_token_file_holding_one_real_character(
    tmp_path: Path,
) -> None:
    """One non-newline character clears the emptiness guard, so the failure that
    follows is a parse failure and not a missing-file failure."""
    token = tmp_path / "token.json"
    # Uppercase X on purpose. The guard asks whether any character lies outside
    # "\r\n", so a mutant that widens that literal to include X treats this file as
    # empty while the original treats it as content. A lowercase x is outside both.
    token.write_text("X\n", encoding="utf-8")

    assert passive_auth_probe(_oauth_upstream(token), environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "invalid OAuth token file for upstream oauth",
    }


def test_passive_auth_probe_rejects_a_required_field_that_is_an_empty_string(
    tmp_path: Path,
) -> None:
    """Present but empty is still missing."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": ""}), encoding="utf-8")

    assert passive_auth_probe(_oauth_upstream(token), environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing OAuth token field for upstream oauth: access_token",
    }


def test_passive_auth_probe_rejects_a_required_field_that_is_not_a_string(
    tmp_path: Path,
) -> None:
    """A non-empty non-string, such as a number, is not a token."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": 12345}), encoding="utf-8")

    assert passive_auth_probe(_oauth_upstream(token), environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing OAuth token field for upstream oauth: access_token",
    }


def test_passive_auth_probe_names_every_missing_required_field(
    tmp_path: Path,
) -> None:
    """The scan covers all required fields, not just the first."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "abc"}), encoding="utf-8")

    assert passive_auth_probe(
        _oauth_upstream(token, required=("access_token", "refresh_token")),
        environ={},
    ) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing OAuth token field for upstream oauth: refresh_token",
    }


def test_passive_auth_probe_accepts_a_complete_token_with_no_expiry_configured(
    tmp_path: Path,
) -> None:
    """With no expiry field configured the expiry branch is skipped entirely."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"access_token": "abc"}), encoding="utf-8")

    assert passive_auth_probe(_oauth_upstream(token), environ={}) == {
        "auth_probe": "credentials_present"
    }


def test_passive_auth_probe_reports_invalid_when_the_expiry_cannot_be_parsed(
    tmp_path: Path,
) -> None:
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps({"access_token": "abc", "expires_at": "not-a-date"}), encoding="utf-8"
    )

    assert passive_auth_probe(
        _oauth_upstream(token, expiry_field="expires_at"), environ={}
    ) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": (
            "invalid OAuth refresh-token expiry for upstream oauth: expires_at"
        ),
    }


def test_passive_auth_probe_accepts_an_expiry_one_second_in_the_future(
    tmp_path: Path,
) -> None:
    """The comparison is inclusive, so strictly-later must still be valid. Paired
    with the equal-to-now case above, this pins the boundary from both sides."""
    now = RealDateTime(2026, 1, 1, tzinfo=timezone.utc)
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps({"access_token": "abc", "expires_at": "2026-01-01T00:00:01Z"}),
        encoding="utf-8",
    )

    assert passive_auth_probe(
        _oauth_upstream(token, expiry_field="expires_at"), environ={}, now=now
    ) == {"auth_probe": "credentials_present"}


def test_passive_auth_probe_reports_expired_for_an_expiry_in_the_past(
    tmp_path: Path,
) -> None:
    now = RealDateTime(2026, 1, 1, tzinfo=timezone.utc)
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps({"access_token": "abc", "expires_at": "2025-12-31T23:59:59Z"}),
        encoding="utf-8",
    )

    assert passive_auth_probe(
        _oauth_upstream(token, expiry_field="expires_at"), environ={}, now=now
    ) == {
        "auth_probe": "oauth_refresh_expired",
        "auth_state": "unauthenticated",
        "last_error": "expired OAuth refresh token for upstream oauth",
    }


def test_passive_auth_probe_rejects_a_token_file_holding_a_json_list(
    tmp_path: Path,
) -> None:
    """Valid JSON that is not an object is not a token document."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps(["access_token"]), encoding="utf-8")

    assert passive_auth_probe(_oauth_upstream(token), environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "invalid OAuth token file for upstream oauth",
    }


def test_passive_auth_probe_reports_auth_repair_when_that_is_the_only_input() -> None:
    """The auth_repair branch is reached only after env, env_files and
    request_meta have all been found empty."""
    upstream = UpstreamConfig(
        name="repairable",
        command="repairable",
        auth_repair=AuthRepairPolicy(tool="setup_auth", trigger_errors=("nope",)),
    )

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "auth_repair_configured"
    }


def test_passive_auth_probe_reports_missing_env_source_by_name() -> None:
    """An env source that is declared but absent from the environment is named."""
    upstream = UpstreamConfig(
        name="keyed", command="keyed", env={"TOKEN": "UPSTREAM_TOKEN"}
    )

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing auth source for upstream keyed: env:UPSTREAM_TOKEN",
    }


def test_passive_auth_probe_treats_an_empty_env_value_as_missing() -> None:
    """Set but empty is not a credential."""
    upstream = UpstreamConfig(
        name="keyed", command="keyed", env={"TOKEN": "UPSTREAM_TOKEN"}
    )

    assert passive_auth_probe(upstream, environ={"UPSTREAM_TOKEN": ""}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing auth source for upstream keyed: env:UPSTREAM_TOKEN",
    }


def test_passive_auth_probe_reports_present_when_the_env_source_is_populated() -> None:
    upstream = UpstreamConfig(
        name="keyed", command="keyed", env={"TOKEN": "UPSTREAM_TOKEN"}
    )

    assert passive_auth_probe(upstream, environ={"UPSTREAM_TOKEN": "value"}) == {
        "auth_probe": "credentials_present"
    }


def test_passive_auth_probe_joins_two_missing_token_fields_with_a_comma_and_space(
    tmp_path: Path,
) -> None:
    """Two missing fields, so the separator itself is observable. With a single
    field the join separator can be anything and no assertion notices."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"unrelated": "x"}), encoding="utf-8")

    assert passive_auth_probe(
        _oauth_upstream(token, required=("access_token", "refresh_token")),
        environ={},
    ) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": (
            "missing OAuth token field for upstream oauth: access_token, refresh_token"
        ),
    }


def test_passive_auth_probe_joins_two_missing_auth_sources_with_a_comma_and_space() -> None:
    """The same separator in the other message. Two declared env sources, both absent."""
    upstream = UpstreamConfig(
        name="keyed",
        command="keyed",
        env={"TOKEN": "UPSTREAM_TOKEN", "EXTRA": "UPSTREAM_EXTRA"},
    )

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": (
            "missing auth source for upstream keyed: "
            "env:UPSTREAM_TOKEN, env:UPSTREAM_EXTRA"
        ),
    }
