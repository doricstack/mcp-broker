from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_remote_broker_auth_can_be_configured_without_remote_listener(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
runtime:
  root: /tmp/mcp-broker-test
broker:
  remote_auth:
    enabled: true
    token_file: "{runtime.secrets_dir}/broker-remote-token"
upstreams: {}
""".strip(),
        encoding="utf-8",
    )

    config = BrokerConfig.from_file(config_file)

    assert config.broker.remote_auth.enabled is True
    assert config.broker.remote_auth.required is True
    assert config.broker.remote_auth.token_env is None
    assert config.broker.remote_auth.token_file == Path(
        "/tmp/mcp-broker-test/secrets/broker-remote-token"
    )


def test_remote_broker_auth_accepts_host_environment_token_source(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
runtime:
  root: /tmp/mcp-broker-test
broker:
  remote_auth:
    enabled: true
    token_env: MCP_BROKER_REMOTE_TOKEN
upstreams: {}
""".strip(),
        encoding="utf-8",
    )

    config = BrokerConfig.from_file(config_file)

    assert config.broker.remote_auth.token_env == "MCP_BROKER_REMOTE_TOKEN"
    assert config.broker.remote_auth.token_file is None


@pytest.mark.parametrize(
    ("broker_yaml", "error"),
    [
        (
            """
broker:
  remote_auth: true
""".strip(),
            "broker.remote_auth must be a mapping",
        ),
        (
            """
broker:
  remote_auth:
    required: false
""".strip(),
            "broker.remote_auth.required must be true",
        ),
        (
            """
broker:
  remote_auth:
    enabled: true
""".strip(),
            "broker.remote_auth requires token_env or token_file when enabled",
        ),
        (
            """
broker:
  remote_auth:
    enabled: true
    token_env: "not valid"
""".strip(),
            "broker.remote_auth.token_env must name a host environment variable",
        ),
    ],
)
def test_remote_broker_auth_rejects_unsafe_config(
    tmp_path: Path,
    broker_yaml: str,
    error: str,
) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        f"""
runtime:
  root: /tmp/mcp-broker-test
{broker_yaml}
upstreams: {{}}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=error):
        BrokerConfig.from_file(config_file)
