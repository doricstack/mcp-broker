from pathlib import Path

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
