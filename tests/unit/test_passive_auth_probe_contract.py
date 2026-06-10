from pathlib import Path
from datetime import datetime, timezone
import json

import pytest


pytestmark = pytest.mark.unit


def test_passive_auth_probe_reports_missing_sources_without_secret_values(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    missing_secret = tmp_path / "secrets" / "API_TOKEN"
    upstream = UpstreamConfig(
        name="api",
        command="api",
        env={"API_TOKEN": "HOST_API_TOKEN"},
        env_files={"FILE_TOKEN": missing_secret},
    )

    probe = passive_auth_probe(upstream, environ={})

    assert probe == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing auth source for upstream api: env:HOST_API_TOKEN, secret_file:FILE_TOKEN",
    }
    serialized = repr(probe)
    assert "secret-value" not in serialized
    assert str(missing_secret) not in serialized


def test_passive_auth_probe_reports_present_credentials_without_reading_them(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    secret_file = tmp_path / "secrets" / "API_TOKEN"
    secret_file.parent.mkdir()
    secret_file.write_text("secret-value\n", encoding="utf-8")
    upstream = UpstreamConfig(
        name="api",
        command="api",
        env={"API_TOKEN": "HOST_API_TOKEN"},
        env_files={"FILE_TOKEN": secret_file},
    )

    probe = passive_auth_probe(upstream, environ={"HOST_API_TOKEN": "secret-value"})

    assert probe == {"auth_probe": "credentials_present"}
    assert "secret-value" not in repr(probe)


def test_passive_auth_probe_reports_browser_setup_without_running_it() -> None:
    from mcp_broker.config import AuthRepairPolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_repair=AuthRepairPolicy(
            tool="setup_auth",
            arguments={"show_browser": True},
            trigger_errors=("Not authenticated",),
        ),
    )

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "auth_repair_configured"
    }


def test_passive_auth_probe_treats_invalid_secret_file_source_as_missing() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    upstream = UpstreamConfig(
        name="api",
        command="api",
        env_files={"FILE_TOKEN": object()},
    )

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing auth source for upstream api: secret_file:FILE_TOKEN",
    }


def test_passive_auth_probe_reports_expired_oauth_refresh_token_without_values(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "refresh_token_expires_at": "2026-05-24T00:00:00Z",
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
            refresh_token_expiry_field="refresh_token_expires_at",
            required_fields=("access_token", "refresh_token"),
        ),
    )

    probe = passive_auth_probe(
        upstream,
        environ={},
        now=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    assert probe == {
        "auth_probe": "oauth_refresh_expired",
        "auth_state": "unauthenticated",
        "last_error": "expired OAuth refresh token for upstream oauth",
    }
    serialized = repr(probe)
    assert "access-secret" not in serialized
    assert "refresh-secret" not in serialized
    assert str(token_file) not in serialized


def test_passive_auth_probe_reports_valid_oauth_token_file_without_values(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "refresh_token_expires_at": "2026-05-26T00:00:00Z",
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
            refresh_token_expiry_field="refresh_token_expires_at",
            required_fields=("access_token", "refresh_token"),
        ),
    )

    probe = passive_auth_probe(
        upstream,
        environ={},
        now=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )

    assert probe == {"auth_probe": "credentials_present"}
    assert "access-secret" not in repr(probe)


def test_passive_auth_probe_reports_invalid_oauth_token_file_without_path(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text("{bad", encoding="utf-8")
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("access_token",),
        ),
    )

    probe = passive_auth_probe(upstream, environ={})

    assert probe == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "invalid OAuth token file for upstream oauth",
    }
    assert str(token_file) not in repr(probe)


def test_passive_auth_probe_treats_single_char_token_file_as_present_but_invalid(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    # A single non-newline character is content, not emptiness: the probe must
    # treat it as a present-but-unparseable token ("invalid"), not "missing".
    token_file = tmp_path / "oauth.json"
    token_file.write_text("X", encoding="utf-8")
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("access_token",),
        ),
    )

    probe = passive_auth_probe(upstream, environ={})

    assert probe == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "invalid OAuth token file for upstream oauth",
    }


def test_passive_auth_probe_treats_newline_only_token_file_as_missing(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    # A file containing only newlines has no token value: it must read as
    # "missing", not "invalid" (which is what a non-empty unparseable file gives).
    token_file = tmp_path / "oauth.json"
    token_file.write_text("\n\n", encoding="utf-8")
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("access_token",),
        ),
    )

    probe = passive_auth_probe(upstream, environ={})

    assert probe == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing OAuth token file for upstream oauth",
    }


def test_passive_auth_probe_reports_missing_oauth_token_file_without_path(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "missing-oauth.json"
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("access_token",),
        ),
    )

    probe = passive_auth_probe(upstream, environ={})

    assert probe == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "missing OAuth token file for upstream oauth",
    }
    assert str(token_file) not in repr(probe)


def test_passive_auth_probe_reports_non_object_oauth_token_file(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text("[]", encoding="utf-8")
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(type="oauth_token_file", token_file=token_file),
    )

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": "invalid OAuth token file for upstream oauth",
    }


def test_passive_auth_probe_reports_missing_oauth_required_fields(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text(json.dumps({"access_token": ""}), encoding="utf-8")
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("access_token", "refresh_token"),
        ),
    )

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": (
            "missing OAuth token field for upstream oauth: "
            "access_token, refresh_token"
        ),
    }


@pytest.mark.parametrize("expiry_value", ["bad-date", ""])
def test_passive_auth_probe_reports_invalid_oauth_refresh_expiry(
    tmp_path: Path,
    expiry_value: str,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text(
        json.dumps(
            {
                "refresh_token": "refresh-secret",
                "refresh_token_expires_at": expiry_value,
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

    assert passive_auth_probe(upstream, environ={}) == {
        "auth_probe": "credentials_missing",
        "auth_state": "unauthenticated",
        "last_error": (
            "invalid OAuth refresh-token expiry for upstream oauth: "
            "refresh_token_expires_at"
        ),
    }


def test_passive_auth_probe_accepts_numeric_oauth_refresh_expiry(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text(
        json.dumps({"refresh_token": "refresh-secret", "refresh_token_expires_at": 1782432000}),
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
        now=datetime(2026, 5, 25, tzinfo=timezone.utc),
    ) == {"auth_probe": "credentials_present"}


def test_passive_auth_probe_accepts_naive_oauth_refresh_expiry(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text(
        json.dumps(
            {
                "refresh_token": "refresh-secret",
                "refresh_token_expires_at": "2026-05-26T00:00:00",
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
        now=datetime(2026, 5, 25, tzinfo=timezone.utc),
    ) == {"auth_probe": "credentials_present"}


def test_passive_auth_probe_accepts_oauth_token_file_without_expiry_field(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import AuthProbePolicy, UpstreamConfig
    from mcp_broker.daemon_helpers import passive_auth_probe

    token_file = tmp_path / "oauth.json"
    token_file.write_text(json.dumps({"access_token": "access-secret"}), encoding="utf-8")
    upstream = UpstreamConfig(
        name="oauth",
        command="oauth",
        auth_probe=AuthProbePolicy(
            type="oauth_token_file",
            token_file=token_file,
            required_fields=("access_token",),
        ),
    )

    assert passive_auth_probe(upstream, environ={}) == {"auth_probe": "credentials_present"}
