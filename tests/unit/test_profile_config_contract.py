from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_broker_config_loads_file_backed_profile_definitions(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
runtime:
  root: /tmp/mcp-broker-test
profiles:
  codex:
    max_tools: 80
    compact_tools_enabled: true
    broker_tool_name_style: snake
  maintenance:
    max_tools: 200
    allow_mutating_upstreams:
      - notes-writer
upstreams:
  read-store:
    command: /tmp/read-store-mcp
    mode: shared
    transport: stdio
    tool_prefix: read-store
    state_dir: upstreams/read-store
    profiles: [codex, maintenance]
  notes-writer:
    command: /tmp/notes-writer-mcp
    mode: per_session
    transport: stdio
    tool_prefix: notes-writer
    state_dir: upstreams/notes-writer
    profiles: [maintenance]
    mutating: true
""".strip(),
        encoding="utf-8",
    )

    config = BrokerConfig.from_file(config_file)

    assert sorted(config.profiles) == ["codex", "maintenance"]
    assert config.profiles["codex"].max_tools == 80
    assert config.profiles["codex"].compact_tools_enabled is True
    assert config.profiles["codex"].broker_tool_name_style == "snake"
    assert config.profiles["maintenance"].max_tools == 200
    assert config.profiles["maintenance"].compact_tools_enabled is False
    assert config.profiles["maintenance"].broker_tool_name_style == "dotted"
    assert config.profiles["maintenance"].allow_mutating_upstreams == ("notes-writer",)
    assert config.upstreams["notes-writer"].mutating is True


def test_expand_text_stops_after_bounded_recursive_environment_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.config import _expand_text

    monkeypatch.setenv("MCP_BROKER_CHAIN_A", "$MCP_BROKER_CHAIN_B")
    monkeypatch.setenv("MCP_BROKER_CHAIN_B", "$MCP_BROKER_CHAIN_C")
    monkeypatch.setenv("MCP_BROKER_CHAIN_C", "$MCP_BROKER_CHAIN_D")
    monkeypatch.setenv("MCP_BROKER_CHAIN_D", "$MCP_BROKER_CHAIN_E")
    monkeypatch.setenv("MCP_BROKER_CHAIN_E", "$MCP_BROKER_CHAIN_F")
    monkeypatch.setenv("MCP_BROKER_CHAIN_F", "expanded-too-far")

    assert _expand_text("$MCP_BROKER_CHAIN_A") == "$MCP_BROKER_CHAIN_F"


def test_upstream_config_loads_rich_schema_fields(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    secret_file = tmp_path / "design-tool-token"
    secret_file.write_text("design-tool-file-secret\n", encoding="utf-8")
    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        f"""
runtime:
  root: /tmp/mcp-broker-test
broker: {{}}
upstreams:
  read-store:
    enabled: true
    mode: shared
    transport: stdio
    tool_prefix: read-store
    command: /tmp/read-store-mcp
    serialize_calls: true
    args: []
    state_dir: upstreams/read-store
    profiles:
      - codex
      - claude
    startup_timeout_seconds: 30
    restart:
      max_attempts: 3
      backoff_seconds: 2
    health:
      ready_timeout_seconds: 10
      call_timeout_seconds: 60
      http_retry_attempts: 2
      http_retry_backoff_seconds: 0
    resources:
      idle_timeout_seconds: 900
      cpu_watchdog_percent: 80
      cpu_watchdog_seconds: 10
      memory_ceiling_mb: 512
    env:
      REMOTE_REPO_TOKEN: HOST_REMOTE_REPO_TOKEN
    env_files:
      DESIGN_TOOL_TOKEN: {secret_file}
""".strip(),
        encoding="utf-8",
    )

    config = BrokerConfig.from_file(config_file)
    upstream = config.upstreams["read-store"]

    assert upstream.transport == "stdio"
    assert upstream.serialize_calls is True
    assert upstream.profiles == ("codex", "claude")
    assert upstream.startup_timeout_seconds == 30
    assert upstream.restart.max_attempts == 3
    assert upstream.restart.backoff_seconds == 2
    assert upstream.health.ready_timeout_seconds == 10
    assert upstream.health.call_timeout_seconds == 60
    assert upstream.health.http_retry_attempts == 2
    assert upstream.health.http_retry_backoff_seconds == 0
    assert upstream.resources.idle_timeout_seconds == 900
    assert upstream.resources.cpu_watchdog_percent == 80
    assert upstream.resources.cpu_watchdog_seconds == 10
    assert upstream.resources.memory_ceiling_mb == 512
    assert upstream.env == {
        "REMOTE_REPO_TOKEN": "HOST_REMOTE_REPO_TOKEN",
    }
    assert upstream.env_files == {"DESIGN_TOOL_TOKEN": secret_file}
    assert upstream.resolve_environment(
        {
            "HOST_REMOTE_REPO_TOKEN": "remote-repo-secret",
        }
    ) == {
        "DESIGN_TOOL_TOKEN": "design-tool-file-secret",
        "REMOTE_REPO_TOKEN": "remote-repo-secret",
    }


def test_upstream_environment_resolution_requires_secret_files(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    missing_secret = tmp_path / "missing-token"
    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        f"""
runtime:
  root: /tmp/mcp-broker-test
upstreams:
  design-tool:
    command: /tmp/design-tool
    env_files:
      DESIGN_TOOL_TOKEN: {missing_secret}
""".strip(),
        encoding="utf-8",
    )

    upstream = BrokerConfig.from_file(config_file).upstreams["design-tool"]

    with pytest.raises(ValueError, match="missing secret file for upstream design-tool"):
        upstream.resolve_environment({})


def test_upstream_environment_resolution_rejects_empty_secret_file(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    secret_file = tmp_path / "empty-token"
    secret_file.write_text("", encoding="utf-8")
    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        f"""
runtime:
  root: /tmp/mcp-broker-test
upstreams:
  design-tool:
    command: /tmp/design-tool
    env_files:
      DESIGN_TOOL_TOKEN: {secret_file}
""".strip(),
        encoding="utf-8",
    )

    upstream = BrokerConfig.from_file(config_file).upstreams["design-tool"]

    with pytest.raises(ValueError, match="missing secret file for upstream design-tool"):
        upstream.resolve_environment({})


def test_upstream_environment_rejects_duplicate_env_sources(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    secret_file = tmp_path / "design-tool-token"
    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        f"""
runtime:
  root: /tmp/mcp-broker-test
upstreams:
  design-tool:
    command: /tmp/design-tool
    env:
      DESIGN_TOOL_TOKEN: HOST_DESIGN_TOOL_TOKEN
    env_files:
      DESIGN_TOOL_TOKEN: {secret_file}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate env source for upstream design-tool"):
        BrokerConfig.from_file(config_file)


@pytest.mark.parametrize(
    ("env_files", "message"),
    [
        ("[]", "upstreams.design-tool.env_files must be a mapping"),
        ("{1: /tmp/secret}", "upstreams.design-tool.env_files keys must be environment variable names"),
    ],
)
def test_upstream_environment_file_config_validation(
    tmp_path: Path,
    env_files: str,
    message: str,
) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        f"""
runtime:
  root: /tmp/mcp-broker-test
upstreams:
  design-tool:
    command: /tmp/design-tool
    env_files: {env_files}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        BrokerConfig.from_file(config_file)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: websocket
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [generic-client]
""".strip(),
            "upstreams.bad.transport",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: serialized_shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [generic-client]
""".strip(),
            "upstreams.bad.mode",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: []
""".strip(),
            "upstreams.bad.profiles",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [""]
""".strip(),
            "upstreams.bad.profiles",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    restart:
      max_attempts: -1
""".strip(),
            "upstreams.bad.restart.max_attempts",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    restart: []
""".strip(),
            "upstreams.bad.restart",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    health:
      call_timeout_seconds: 0
""".strip(),
            "upstreams.bad.health.call_timeout_seconds",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: http
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    health:
      http_retry_attempts: -1
""".strip(),
            "upstreams.bad.health.http_retry_attempts",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: http
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    health:
      http_retry_backoff_seconds: -1
""".strip(),
            "upstreams.bad.health.http_retry_backoff_seconds",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    resources:
      cpu_watchdog_percent: 101
""".strip(),
            "upstreams.bad.resources.cpu_watchdog_percent",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    resources:
      memory_ceiling_mb: 0
""".strip(),
            "upstreams.bad.resources.memory_ceiling_mb",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    serialize_calls: "yes"
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
""".strip(),
            "upstreams.bad.serialize_calls",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    env: []
""".strip(),
            "upstreams.bad.env",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    env:
      "": MCP_TOKEN
""".strip(),
            "upstreams.bad.env",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    env:
      TOKEN: sk-secret
""".strip(),
            "upstreams.bad.env.TOKEN",
        ),
        (
            """
runtime:
  root: /tmp/x
upstreams:
  bad:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: bad
    state_dir: upstreams/bad
    profiles: [codex]
    mutating: "false"
""".strip(),
            "upstreams.bad.mutating must be a boolean",
        ),
    ],
)
def test_upstream_config_rejects_invalid_rich_schema_fields(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        BrokerConfig.from_file(config_file)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            """
runtime:
  root: /tmp/x
profiles: []
""".strip(),
            "profiles must be a mapping",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex: []
""".strip(),
            "profiles.codex must be a mapping",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    compact_tools_enabled: true
""".strip(),
            "profiles.codex.max_tools",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    max_tools: 0
""".strip(),
            "profile max_tools must be greater than 0",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    max_tools: 10
    broker_tool_name_style: camel
""".strip(),
            "profile broker_tool_name_style must be one of: dotted, snake",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    max_tools: 10
    broker_tool_name_style: []
""".strip(),
            "profile broker_tool_name_style must be a string",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    max_tools: 10
    allow_mutating_upstreams: notes-writer
""".strip(),
            "profiles.codex.allow_mutating_upstreams must be a list",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    max_tools: 10
    allow_mutating_upstreams:
      - ""
""".strip(),
            "profiles.codex.allow_mutating_upstreams must contain upstream names",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    max_tools: 10
upstreams:
  read-store:
    command: /tmp/read-store-mcp
    mode: shared
    transport: stdio
    tool_prefix: read-store
    state_dir: upstreams/read-store
    profiles: [codexx]
""".strip(),
            "upstreams.read-store.profiles references undefined profile: codexx",
        ),
        (
            """
runtime:
  root: /tmp/x
profiles:
  codex:
    max_tools: 10
upstreams:
  notes-writer:
    command: /tmp/notes-writer-mcp
    mode: per_session
    transport: stdio
    tool_prefix: notes-writer
    state_dir: upstreams/notes-writer
    profiles: [codex]
    mutating: true
""".strip(),
            "mutating upstream notes-writer requires profile allowlist entry: codex",
        ),
    ],
)
def test_broker_config_rejects_invalid_profile_definitions(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        BrokerConfig.from_file(config_file)


def test_upstream_environment_resolution_requires_named_host_variables(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
runtime:
  root: /tmp/x
upstreams:
  fake:
    command: /tmp/tool
    mode: shared
    transport: stdio
    tool_prefix: fake
    state_dir: upstreams/fake
    profiles: [manual-test]
    env:
      TARGET_TOKEN: SOURCE_TOKEN
""".strip(),
        encoding="utf-8",
    )
    upstream = BrokerConfig.from_file(config_file).upstreams["fake"]

    with pytest.raises(ValueError, match="missing environment variable for upstream fake: SOURCE_TOKEN"):
        upstream.resolve_environment({})


def test_broker_config_rejects_duplicate_profile_prefixes(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
runtime:
  root: /tmp/x
upstreams:
  one:
    command: /tmp/one
    mode: shared
    transport: stdio
    tool_prefix: dup
    state_dir: upstreams/one
    profiles: [codex]
  two:
    command: /tmp/two
    mode: shared
    transport: stdio
    tool_prefix: dup
    state_dir: upstreams/two
    profiles: [codex]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate tool prefix for profile codex: dup"):
        BrokerConfig.from_file(config_file)
