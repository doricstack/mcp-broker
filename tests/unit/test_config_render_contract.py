import argparse
from dataclasses import replace
import json
from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_render_rejects_unknown_client(tmp_path: Path) -> None:
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)

    with pytest.raises(ValueError, match="unknown client config: missing"):
        render_client_config(config, client_name="missing", dry_run=True)


def test_render_rejects_unsupported_client_format(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)
    broken = BrokerConfig(
        runtime=config.runtime,
        broker=config.broker,
        upstreams=config.upstreams,
        clients={"codex": replace(config.clients["codex"], format="ini")},
    )

    with pytest.raises(ValueError, match="unsupported client config format: ini"):
        render_client_config(broken, client_name="codex", dry_run=True)


def test_config_render_subcommands_parse_exact_command_contract() -> None:
    from mcp_broker.config_render import _add_subcommands

    parser = _config_render_parser()

    backup = parser.parse_args(["backup", "--config", "cfg.yaml", "--client", "codex", "--label", "L"])
    assert vars(backup) == {
        "command": "backup",
        "config": "cfg.yaml",
        "client": "codex",
        "label": "L",
    }

    dry_render = parser.parse_args(["render", "--config", "cfg.yaml", "--client", "codex"])
    assert vars(dry_render) == {
        "command": "render",
        "config": "cfg.yaml",
        "client": "codex",
        "apply": False,
        "target_path": None,
    }

    apply_render = parser.parse_args(
        [
            "render",
            "--config",
            "cfg.yaml",
            "--client",
            "codex",
            "--apply",
            "--target-path",
            "/tmp/project.toml",
        ]
    )
    assert vars(apply_render) == {
        "command": "render",
        "config": "cfg.yaml",
        "client": "codex",
        "apply": True,
        "target_path": "/tmp/project.toml",
    }

    app_policy = parser.parse_args(
        ["app-policy", "--config", "cfg.yaml", "--client", "codex", "--apply", "--label", "L"]
    )
    assert vars(app_policy) == {
        "command": "app-policy",
        "config": "cfg.yaml",
        "client": "codex",
        "apply": True,
        "label": "L",
    }

    rollback = parser.parse_args(["rollback", "--config", "cfg.yaml", "--client", "codex"])
    assert vars(rollback) == {
        "command": "rollback",
        "config": "cfg.yaml",
        "client": "codex",
    }

    help_text = parser.format_help()
    assert "{backup,render,app-policy,rollback}" in help_text


def test_config_render_subcommands_require_config_and_client() -> None:
    parser = _config_render_parser()

    for argv in (
        ["backup", "--client", "codex"],
        ["backup", "--config", "cfg.yaml"],
        ["render", "--client", "codex"],
        ["render", "--config", "cfg.yaml"],
        ["app-policy", "--client", "codex"],
        ["app-policy", "--config", "cfg.yaml"],
        ["rollback", "--client", "codex"],
        ["rollback", "--config", "cfg.yaml"],
    ):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(argv)
        assert exc_info.value.code == 2


def test_config_render_main_requires_command_and_exposes_help_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.config_render import CONFIG_RENDER_DESCRIPTION, main

    with pytest.raises(SystemExit) as missing_command:
        main([])
    assert missing_command.value.code == 2

    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    assert CONFIG_RENDER_DESCRIPTION in capsys.readouterr().out


def test_config_render_constants_are_public_contract() -> None:
    from mcp_broker.config_render import CONFIG_RENDER_DESCRIPTION, TEXT_ENCODING, TIMESTAMP_FORMAT

    assert CONFIG_RENDER_DESCRIPTION == "Render or roll back MCP client configs"
    assert TEXT_ENCODING == "utf-8"
    assert TIMESTAMP_FORMAT == "%Y%m%dT%H%M%SZ"


def test_timestamp_label_uses_utc_and_release_label_format(monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_broker.config_render as config_render

    class RecordingDateTime:
        timezone_seen = None
        format_seen = None

        @classmethod
        def now(cls, timezone_value):
            cls.timezone_seen = timezone_value
            return cls()

        def strftime(self, format_value: str) -> str:
            type(self).format_seen = format_value
            return "20260525T111213Z"

    monkeypatch.setattr(config_render, "datetime", RecordingDateTime)

    assert config_render._timestamp_label() == "20260525T111213Z"
    assert RecordingDateTime.timezone_seen is config_render.timezone.utc
    assert RecordingDateTime.format_seen == config_render.TIMESTAMP_FORMAT


def test_strip_codex_mcp_tables_removes_only_mcp_tables_and_legacy_blocks() -> None:
    from mcp_broker.config_render import _strip_codex_mcp_tables

    assert _strip_codex_mcp_tables(
        'model = "configured"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "# === MCP servers (synced from ~/mcp/servers.json + project .mcp.json files) ===\n"
        "# generated legacy comment\n"
        "[mcp_servers]\n"
        'command = "root-direct"\n'
        "\n"
        '[mcp_servers."direct-tool"]\n'
        'command = "direct-tool"\n'
        "\n"
        "[profiles.prod]\n"
        'approval_policy = "never"\n'
    ) == (
        'model = "configured"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n'
        "\n"
        "[profiles.prod]\n"
        'approval_policy = "never"\n'
    )


def test_strip_codex_mcp_tables_preserves_pending_separator_when_not_legacy() -> None:
    from mcp_broker.config_render import _strip_codex_mcp_tables

    assert _strip_codex_mcp_tables(
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "[profiles.dev]\n"
        'model = "configured"\n'
    ) == (
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "[profiles.dev]\n"
        'model = "configured"\n'
    )


def test_strip_codex_mcp_tables_preserves_leading_whitespace_and_malformed_headers() -> None:
    from mcp_broker.config_render import _strip_codex_mcp_tables

    assert _strip_codex_mcp_tables(
        "\n"
        "  # local setting\n"
        "[mcp_servers\n"
        'command = "not-a-table"\n'
        "not-a-table]\n"
        "\n"
        "[profiles.dev]\n"
        'model = "configured"\n'
    ) == (
        "\n"
        "  # local setting\n"
        "[mcp_servers\n"
        'command = "not-a-table"\n'
        "not-a-table]\n"
        "\n"
        "[profiles.dev]\n"
        'model = "configured"\n'
    )


def test_strip_codex_mcp_tables_keeps_legacy_block_until_valid_table_header() -> None:
    from mcp_broker.config_render import _strip_codex_mcp_tables

    assert _strip_codex_mcp_tables(
        'model = "configured"\n'
        "# === MCP servers (synced from ~/mcp/servers.json + project .mcp.json files) ===\n"
        "[not-a-table\n"
        "not-a-table]\n"
        "comment in legacy block\n"
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n'
    ) == (
        'model = "configured"\n'
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n'
    )


def test_strip_trailing_separator_comments_removes_repeated_trailing_blocks() -> None:
    from mcp_broker.config_render import _strip_trailing_separator_comments

    assert _strip_trailing_separator_comments(
        'model = "configured"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
    ) == 'model = "configured"\n'


def test_strip_trailing_separator_comments_preserves_leading_blank_lines() -> None:
    from mcp_broker.config_render import _strip_trailing_separator_comments

    assert _strip_trailing_separator_comments(
        "\n"
        'model = "configured"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
    ) == "\n" 'model = "configured"\n'


def test_render_claude_json_preserves_settings_and_sorts_keys() -> None:
    from mcp_broker.config_render import _render_claude_json

    rendered = _render_claude_json(
        "mcp-broker",
        "mcp-broker-client",
        ["--profile", "codex"],
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {"direct": {"command": "direct-client"}},
            }
        ),
    )

    assert rendered == json.dumps(
        {
            "mcpServers": {
                "mcp-broker": {
                    "args": ["--profile", "codex"],
                    "command": "mcp-broker-client",
                }
            },
            "theme": "dark",
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def test_render_mcp_settings_json_preserves_settings_and_allowed_policy() -> None:
    from mcp_broker.client_config import ClientRenderConfig
    from mcp_broker.config_render import _render_mcp_settings_json

    rendered = _render_mcp_settings_json(
        "mcp-broker",
        "mcp-broker-client",
        ["--profile", "agy"],
        json.dumps(
            {
                "theme": "dark",
                "mcp": {"excluded": ["direct"]},
                "mcpServers": {"direct": {"command": "direct-client"}},
            }
        ),
        ClientRenderConfig(
            name="agy",
            format="mcp-settings-json",
            config_path=Path("settings.json"),
            mcp_allowed_servers=("mcp-broker",),
        ),
    )

    assert rendered == json.dumps(
        {
            "mcp": {"allowed": ["mcp-broker"], "excluded": ["direct"]},
            "mcpServers": {
                "mcp-broker": {
                    "args": ["--profile", "agy"],
                    "command": "mcp-broker-client",
                }
            },
            "theme": "dark",
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def test_render_mcp_settings_json_does_not_create_mcp_policy_without_allowed_servers() -> None:
    from mcp_broker.client_config import ClientRenderConfig
    from mcp_broker.config_render import _render_mcp_settings_json

    rendered = _render_mcp_settings_json(
        "mcp-broker",
        "mcp-broker-client",
        ["--profile", "agy"],
        "{}",
        ClientRenderConfig(
            name="agy",
            format="mcp-settings-json",
            config_path=Path("settings.json"),
        ),
    )

    assert json.loads(rendered) == {
        "mcpServers": {
            "mcp-broker": {
                "args": ["--profile", "agy"],
                "command": "mcp-broker-client",
            }
        }
    }


def test_json_line_serializes_dataclasses_paths_none_and_bool_values() -> None:
    from mcp_broker.config_render import RenderResult, _json_line

    assert _json_line(
        RenderResult(
            client_name="codex",
            target_path=Path("/tmp/target.toml"),
            rendered_path=Path("/tmp/rendered.toml"),
            backup_path=None,
            dry_run=True,
        )
    ) == (
        '{"backup_path": null, "client_name": "codex", "codex_apps_policy_result": null, '
        '"dry_run": true, "rendered_path": "/tmp/rendered.toml", "target_path": "/tmp/target.toml"}\n'
    )


def test_backup_path_creates_empty_backup_for_missing_source(tmp_path: Path) -> None:
    from mcp_broker.config_render import _backup_path

    config = _config(tmp_path)

    backup_path = _backup_path(
        config,
        "codex",
        tmp_path / "missing.toml",
        backup_label="20260525T101010Z",
    )

    assert backup_path == tmp_path / "runtime" / "backups" / "codex" / "20260525T101010Z.missing.toml"
    assert backup_path.parent.is_dir()
    assert backup_path.read_text(encoding="utf-8") == ""


def test_backup_path_generates_utc_label_when_label_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.config_render as config_render

    monkeypatch.setattr(config_render, "_timestamp_label", lambda: "20260525T111213Z")
    config = _config(tmp_path)

    backup_path = config_render._backup_path(
        config,
        "codex",
        tmp_path / "missing.toml",
        backup_label=None,
    )

    assert backup_path == tmp_path / "runtime" / "backups" / "codex" / "20260525T111213Z.missing.toml"
    assert backup_path.read_text(encoding="utf-8") == ""


def test_rollback_restores_latest_lexicographic_backup(tmp_path: Path) -> None:
    from mcp_broker.config_render import rollback_client_config

    config = _config(tmp_path)
    target_path = tmp_path / "codex.toml"
    backup_dir = tmp_path / "runtime" / "backups" / "codex"
    backup_dir.mkdir(parents=True)
    older_backup = backup_dir / "20250101T000000Z.codex.toml"
    newer_backup = backup_dir / "20260101T000000Z.codex.toml"
    older_backup.write_text("older = true\n", encoding="utf-8")
    newer_backup.write_text("newer = true\n", encoding="utf-8")
    target_path.write_text("current = true\n", encoding="utf-8")

    result = rollback_client_config(config, client_name="codex")

    assert result.client_name == "codex"
    assert result.target_path == target_path
    assert result.restored_path == newer_backup
    assert target_path.read_text(encoding="utf-8") == "newer = true\n"


def test_dry_run_render_writes_rendered_artifact_without_target_backup_or_policy(tmp_path: Path) -> None:
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text('model = "configured"\n', encoding="utf-8")

    result = render_client_config(config, client_name="codex", dry_run=True)

    assert result.client_name == "codex"
    assert result.target_path == target_path
    assert result.rendered_path == tmp_path / "runtime" / "renders" / "codex.config.toml"
    assert result.backup_path is None
    assert result.dry_run is True
    assert result.codex_apps_policy_result is None
    assert target_path.read_text(encoding="utf-8") == 'model = "configured"\n'
    assert '[mcp_servers."mcp-broker"]' in result.rendered_path.read_text(encoding="utf-8")


def test_render_text_missing_source_starts_with_broker_entry_only(tmp_path: Path) -> None:
    from mcp_broker.config_render import _render_text

    config = _config(tmp_path)
    client = config.clients["codex"]

    assert _render_text(config, client) == (
        '[mcp_servers."mcp-broker"]\n'
        'command = "mcp-broker-client"\n'
        f'args = ["--socket-path", "{tmp_path}/runtime/sockets/broker.sock"]\n'
    )


def test_codex_render_text_escapes_toml_and_strips_only_mcp_server_tables(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    target_path = tmp_path / "codex.toml"
    target_path.write_text(
        'model = "configured-model"\n'
        "\n"
        "[mcp_servers]\n"
        'command = "remove-root-table"\n'
        "\n"
        '[mcp_servers."direct-reader"]\n'
        'command = "remove-nested-table"\n'
        "\n"
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n',
        encoding="utf-8",
    )
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "toml-client": {
                        "format": "codex-toml",
                        "config_path": str(target_path),
                        "entry_name": 'broker "quoted"',
                        "command": 'client "runner"',
                        "args": [
                            "--socket-path",
                            "{runtime.socket_path}",
                            "--profile",
                            'profile "quoted"',
                            r"C:\client\path",
                        ],
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="toml-client",
        dry_run=True,
    )

    rendered = result.rendered_path.read_text(encoding="utf-8")
    assert 'model = "configured-model"' in rendered
    assert "[profiles.dev]" in rendered
    assert "direct-reader" not in rendered
    assert "remove-root-table" not in rendered
    assert "remove-nested-table" not in rendered
    assert '[mcp_servers."broker \\"quoted\\""]' in rendered
    assert 'command = "client \\"runner\\""' in rendered
    assert (
        f'args = ["--socket-path", "{runtime_root}/sockets/broker.sock", "--profile", '
        '"profile \\"quoted\\"", "C:\\\\client\\\\path"]'
    ) in rendered


def test_codex_mcp_table_classifier_handles_root_nested_and_non_mcp_headers() -> None:
    from mcp_broker.config_render import _is_codex_mcp_table, _is_table_header

    assert _is_table_header("[mcp_servers]") is True
    assert _is_table_header("[mcp_servers") is False
    assert _is_table_header("mcp_servers]") is False
    assert _is_codex_mcp_table("[mcp_servers]") is True
    assert _is_codex_mcp_table('[mcp_servers."generic-tool"]') is True
    assert _is_codex_mcp_table("[profiles.dev]") is False
    assert _is_codex_mcp_table("[mcp_serverish]") is False


def test_mcp_settings_json_render_preserves_client_settings_and_replaces_servers(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    target_path = tmp_path / "settings.json"
    target_path.write_text(
        json.dumps(
            {
                "selectedAuthType": "api-key",
                "mcpServers": {
                    "direct-memory": {
                        "command": "memory-mcp",
                    },
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "json-chat-client": {
                        "format": "mcp-settings-json",
                        "config_path": str(target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                        "args": [
                            "--socket-path",
                            "{runtime.socket_path}",
                            "--profile",
                            "json-chat-client",
                        ],
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="json-chat-client",
        dry_run=True,
    )

    assert json.loads(target_path.read_text(encoding="utf-8"))["mcpServers"] == {
        "direct-memory": {
            "command": "memory-mcp",
        }
    }
    rendered = json.loads(result.rendered_path.read_text(encoding="utf-8"))
    assert rendered == {
        "mcpServers": {
            "mcp-broker": {
                "args": [
                    "--socket-path",
                    str(runtime_root / "sockets" / "broker.sock"),
                    "--profile",
                    "json-chat-client",
                ],
                "command": "mcp-broker-client",
            }
        },
        "selectedAuthType": "api-key",
    }


def test_agy_settings_json_apply_writes_allowed_broker_and_backup(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    target_path = tmp_path / "settings.json"
    target_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcp": {"excluded": ["legacy-direct"]},
                "mcpServers": {"legacy-direct": {"command": "legacy-client"}},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "agy": {
                        "format": "mcp-settings-json",
                        "config_path": str(target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                        "args": [
                            "--socket-path",
                            "{runtime.socket_path}",
                            "--profile",
                            "agy",
                        ],
                        "mcp_allowed_servers": ["mcp-broker"],
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="agy",
        dry_run=False,
        backup_label="20260525T010101Z",
    )

    assert result.backup_path == runtime_root / "backups" / "agy" / "20260525T010101Z.settings.json"
    assert json.loads(result.backup_path.read_text(encoding="utf-8"))["mcpServers"] == {
        "legacy-direct": {"command": "legacy-client"}
    }
    rendered = json.loads(target_path.read_text(encoding="utf-8"))
    assert rendered == {
        "mcp": {"allowed": ["mcp-broker"], "excluded": ["legacy-direct"]},
        "mcpServers": {
            "mcp-broker": {
                "args": [
                    "--socket-path",
                    str(runtime_root / "sockets" / "broker.sock"),
                    "--profile",
                    "agy",
                ],
                "command": "mcp-broker-client",
            }
        },
        "theme": "dark",
    }


def test_render_client_config_uses_explicit_text_encoding_for_reads_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.config_render as config_render

    config = _config(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text('model = "configured"\n', encoding="utf-8")
    missing_source = tmp_path / "missing.toml"
    rendered_path = tmp_path / "runtime" / "renders" / "codex.config.toml"
    missing_backup_path = tmp_path / "runtime" / "backups" / "codex" / "20260525T121212Z.missing.toml"
    real_read_text = Path.read_text
    real_write_text = Path.write_text
    read_paths: list[Path] = []
    write_paths: list[Path] = []

    def checked_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == target_path:
            assert kwargs.get("encoding") == config_render.TEXT_ENCODING
            read_paths.append(self)
        return real_read_text(self, *args, **kwargs)

    def checked_write_text(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if self in {rendered_path, target_path, missing_backup_path}:
            assert kwargs.get("encoding") == config_render.TEXT_ENCODING
            write_paths.append(self)
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", checked_read_text)
    monkeypatch.setattr(Path, "write_text", checked_write_text)

    config_render.render_client_config(
        config,
        client_name="codex",
        dry_run=False,
        backup_label="20260525T121212Z",
    )
    config_render._backup_path(
        config,
        "codex",
        missing_source,
        backup_label="20260525T121212Z",
    )

    assert read_paths == [target_path]
    assert rendered_path in write_paths
    assert target_path in write_paths
    assert missing_backup_path in write_paths


def test_claude_render_preserves_user_settings_replaces_servers_and_records_backup(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    target_path = tmp_path / "claude.json"
    target_path.write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {"legacy-direct": {"command": "legacy-client"}},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "claude": {
                        "format": "claude-json",
                        "config_path": str(target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                        "args": [
                            "--socket-path",
                            "{runtime.socket_path}",
                            "--profile",
                            "claude",
                        ],
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="claude",
        dry_run=False,
        backup_label="20260525T020202Z",
    )

    assert result.backup_path == runtime_root / "backups" / "claude" / "20260525T020202Z.claude.json"
    assert json.loads(result.backup_path.read_text(encoding="utf-8"))["mcpServers"] == {
        "legacy-direct": {"command": "legacy-client"}
    }
    assert json.loads(target_path.read_text(encoding="utf-8")) == {
        "mcpServers": {
            "mcp-broker": {
                "args": [
                    "--socket-path",
                    str(runtime_root / "sockets" / "broker.sock"),
                    "--profile",
                    "claude",
                ],
                "command": "mcp-broker-client",
            }
        },
        "theme": "dark",
    }


def test_apply_render_creates_nested_override_target_parent(tmp_path: Path) -> None:
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)
    override_path = tmp_path / "clients" / "nested" / "codex.toml"

    result = render_client_config(
        config,
        client_name="codex",
        dry_run=False,
        target_path=override_path,
        backup_label="20260525T131313Z",
    )

    assert result.target_path == override_path
    assert override_path.read_text(encoding="utf-8").startswith('[mcp_servers."mcp-broker"]\n')
    assert result.backup_path == (
        tmp_path / "runtime" / "backups" / "codex" / "20260525T131313Z.codex.toml"
    )


def test_mcp_settings_json_render_can_write_allowed_mcp_server_policy(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    target_path = tmp_path / "settings.json"
    target_path.write_text(
        json.dumps(
            {
                "mcp": {
                    "excluded": ["legacy-server"],
                },
                "mcpServers": {
                    "legacy-server": {
                        "command": "legacy-mcp",
                    },
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "local-chat": {
                        "format": "mcp-settings-json",
                        "config_path": str(target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                        "args": [
                            "--socket-path",
                            "{runtime.socket_path}",
                            "--profile",
                            "local-chat",
                        ],
                        "mcp_allowed_servers": ["mcp-broker"],
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="local-chat",
        dry_run=True,
    )

    rendered = json.loads(result.rendered_path.read_text(encoding="utf-8"))
    assert rendered["mcp"] == {
        "allowed": ["mcp-broker"],
        "excluded": ["legacy-server"],
    }
    assert rendered["mcpServers"] == {
        "mcp-broker": {
            "args": [
                "--socket-path",
                str(runtime_root / "sockets" / "broker.sock"),
                "--profile",
                "local-chat",
            ],
            "command": "mcp-broker-client",
        }
    }


def test_mcp_settings_json_render_recovers_from_invalid_existing_objects(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    list_target_path = tmp_path / "list-settings.json"
    list_target_path.write_text("[]\n", encoding="utf-8")
    bad_mcp_target_path = tmp_path / "bad-mcp-settings.json"
    bad_mcp_target_path.write_text(
        json.dumps({"mcp": [], "mcpServers": {"old": {"command": "old"}}}),
        encoding="utf-8",
    )
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "list-client": {
                        "format": "mcp-settings-json",
                        "config_path": str(list_target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                        "mcp_allowed_servers": ["mcp-broker"],
                    },
                    "bad-mcp-client": {
                        "format": "mcp-settings-json",
                        "config_path": str(bad_mcp_target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                        "mcp_allowed_servers": ["mcp-broker"],
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    list_result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="list-client",
        dry_run=True,
    )
    bad_mcp_result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="bad-mcp-client",
        dry_run=True,
    )

    assert json.loads(list_result.rendered_path.read_text(encoding="utf-8"))["mcp"] == {
        "allowed": ["mcp-broker"],
    }
    assert json.loads(bad_mcp_result.rendered_path.read_text(encoding="utf-8"))["mcp"] == {
        "allowed": ["mcp-broker"],
    }


def test_codex_render_uses_home_relative_socket_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    config_path = tmp_path / "broker.yaml"
    target_path = tmp_path / "codex.toml"
    config_path.write_text(
        f"""
runtime:
  root: $HOME/mcp/mcp-broker
clients:
  codex:
    format: codex-toml
    config_path: {target_path}
    entry_name: mcp-broker
    command: mcp-broker-client
    args:
      - --socket-path
      - "{{runtime.socket_path}}"
      - --profile
      - codex
upstreams: {{}}
""".strip(),
        encoding="utf-8",
    )

    result = render_client_config(BrokerConfig.from_file(config_path), client_name="codex", dry_run=True)

    rendered = result.rendered_path.read_text(encoding="utf-8")
    assert f"{home}/mcp/mcp-broker/sockets/broker.sock" not in rendered
    assert 'args = ["--socket-path", "$HOME/mcp/mcp-broker/sockets/broker.sock", "--profile", "codex"]' in rendered


def test_portable_client_arg_preserves_paths_when_home_is_root(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_broker.config_render import _portable_client_arg

    monkeypatch.setenv("HOME", "/")

    assert _portable_client_arg("/runtime/sockets/broker.sock") == "/runtime/sockets/broker.sock"


def test_portable_client_arg_can_render_home_itself(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.config_render import _portable_client_arg

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    assert _portable_client_arg(str(home)) == "$HOME"


def test_apply_render_can_backup_missing_target_as_empty_file(tmp_path: Path) -> None:
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)

    result = render_client_config(
        config,
        client_name="codex",
        dry_run=False,
        backup_label="20260524T010101Z",
    )

    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == ""


def test_apply_render_can_target_an_override_config_path(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    configured_path = tmp_path / "configured-client.toml"
    override_path = tmp_path / "configs" / "config.project-under-test.toml"
    configured_path.write_text("configured = true\n", encoding="utf-8")
    override_path.parent.mkdir()
    override_path.write_text("project = true\n[mcp_servers.read-store]\ncommand = \"read-store\"\n", encoding="utf-8")
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "toml-client": {
                        "format": "codex-toml",
                        "config_path": str(configured_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="toml-client",
        dry_run=False,
        backup_label="20260524T060606Z",
        target_path=override_path,
    )

    assert result.target_path == override_path
    assert configured_path.read_text(encoding="utf-8") == "configured = true\n"
    assert override_path.read_text(encoding="utf-8") == (
        "project = true\n\n"
        '[mcp_servers."mcp-broker"]\n'
        'command = "mcp-broker-client"\n'
        f'args = ["--socket-path", "{runtime_root}/sockets/broker.sock"]\n'
    )
    assert (
        result.backup_path
        == runtime_root / "backups" / "toml-client" / "20260524T060606Z.config.project-under-test.toml"
    )
    assert result.backup_path.read_text(encoding="utf-8") == (
        "project = true\n[mcp_servers.read-store]\ncommand = \"read-store\"\n"
    )


def test_codex_render_drops_legacy_synced_mcp_comment_blocks(tmp_path: Path) -> None:
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text(
        'approval_policy = "never"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "# === MCP servers (synced from ~/mcp/servers.json + project .mcp.json files) ===\n"
        "# Last synced: 2026-05-24 12:47\n"
        "# DO NOT EDIT - modify source files instead, then run sync-to-codex.sh\n"
        "# Secrets resolved at runtime via env-mcp.sh wrapper (no plaintext in this file)\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "# =======================================\n"
        "#   GLOBAL SERVERS (all projects)\n"
        "# =======================================\n"
        "\n"
        "## Enhanced read-store-mcp (local fork runtime, project-scoped SQLite, no runtime npx)\n"
        "\n"
        '[mcp_servers."read-store"]\n'
        'command = "read-store"\n',
        encoding="utf-8",
    )

    render_client_config(config, client_name="codex", dry_run=False)

    assert target_path.read_text(encoding="utf-8") == (
        'approval_policy = "never"\n'
        "\n"
        '[mcp_servers."mcp-broker"]\n'
        'command = "mcp-broker-client"\n'
        f'args = ["--socket-path", "{tmp_path}/runtime/sockets/broker.sock"]\n'
    )


def test_codex_render_drops_trailing_separator_before_broker_entry(tmp_path: Path) -> None:
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text(
        'approval_policy = "never"\n\n# -----------------------------------------------------------------------------\n\n',
        encoding="utf-8",
    )

    render_client_config(config, client_name="codex", dry_run=False)

    assert target_path.read_text(encoding="utf-8") == (
        'approval_policy = "never"\n'
        "\n"
        '[mcp_servers."mcp-broker"]\n'
        'command = "mcp-broker-client"\n'
        f'args = ["--socket-path", "{tmp_path}/runtime/sockets/broker.sock"]\n'
    )


def test_codex_render_preserves_non_legacy_separator_blocks(tmp_path: Path) -> None:
    from mcp_broker.config_render import render_client_config

    config = _config(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text(
        'approval_policy = "never"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n",
        encoding="utf-8",
    )

    render_client_config(config, client_name="codex", dry_run=False)

    assert target_path.read_text(encoding="utf-8") == (
        'approval_policy = "never"\n'
        "\n"
        "# -----------------------------------------------------------------------------\n"
        "\n"
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n'
        "\n"
        '[mcp_servers."mcp-broker"]\n'
        'command = "mcp-broker-client"\n'
        f'args = ["--socket-path", "{tmp_path}/runtime/sockets/broker.sock"]\n'
    )


def test_backup_client_config_copies_target_and_related_paths_without_rendering(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import backup_client_config

    config_path = _config_file(
        tmp_path,
        client_extra={
            "backup_paths": [str(tmp_path / "claude-settings.json"), str(tmp_path / "missing.json")]
        },
    )
    target_path = tmp_path / "codex.toml"
    settings_path = tmp_path / "claude-settings.json"
    target_path.write_text('approval_policy = "never"\n', encoding="utf-8")
    settings_path.write_text('{"theme":"dark"}\n', encoding="utf-8")

    result = backup_client_config(
        BrokerConfig.from_file(config_path),
        client_name="codex",
        backup_label="20260524T020202Z",
    )

    assert result.client_name == "codex"
    assert target_path.read_text(encoding="utf-8") == 'approval_policy = "never"\n'
    assert sorted(path.name for path in result.backup_paths) == [
        "20260524T020202Z.claude-settings.json",
        "20260524T020202Z.codex.toml",
        "20260524T020202Z.missing.json",
    ]
    assert (tmp_path / "runtime" / "backups" / "codex" / "20260524T020202Z.codex.toml").read_text(
        encoding="utf-8"
    ) == 'approval_policy = "never"\n'
    assert (
        tmp_path / "runtime" / "backups" / "codex" / "20260524T020202Z.claude-settings.json"
    ).read_text(encoding="utf-8") == '{"theme":"dark"}\n'
    assert (
        tmp_path / "runtime" / "backups" / "codex" / "20260524T020202Z.missing.json"
    ).read_text(encoding="utf-8") == ""
    assert not (tmp_path / "runtime" / "renders" / "codex.config.toml").exists()


def test_rollback_rejects_missing_backups(tmp_path: Path) -> None:
    from mcp_broker.config_render import rollback_client_config

    config = _config(tmp_path)

    with pytest.raises(ValueError, match="no backups found for client: codex"):
        rollback_client_config(config, client_name="codex")


def test_rollback_creates_nested_target_parent(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import rollback_client_config

    runtime_root = tmp_path / "runtime"
    target_path = tmp_path / "clients" / "nested" / "codex.toml"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "codex": {
                        "format": "codex-toml",
                        "config_path": str(target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    backup_path = runtime_root / "backups" / "codex" / "20260525T141414Z.codex.toml"
    backup_path.parent.mkdir(parents=True)
    backup_path.write_text("restored = true\n", encoding="utf-8")

    result = rollback_client_config(BrokerConfig.from_file(config_path), client_name="codex")

    assert result.target_path == target_path
    assert result.restored_path == backup_path
    assert target_path.read_text(encoding="utf-8") == "restored = true\n"


def test_config_render_cli_outputs_json_for_dry_run_and_rollback(tmp_path: Path) -> None:
    from mcp_broker.config_render import main

    config_path = _config_file(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text("original = true\n", encoding="utf-8")

    assert main(["render", "--config", str(config_path), "--client", "codex"]) == 0
    assert target_path.read_text(encoding="utf-8") == "original = true\n"
    assert main(["render", "--config", str(config_path), "--client", "codex", "--apply"]) == 0
    assert '[mcp_servers."mcp-broker"]' in target_path.read_text(encoding="utf-8")
    assert main(["rollback", "--config", str(config_path), "--client", "codex"]) == 0
    assert target_path.read_text(encoding="utf-8") == "original = true\n"


def test_config_render_cli_target_path_wiring_outputs_one_json_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.config_render import main

    config_path = _config_file(tmp_path)
    configured_path = tmp_path / "codex.toml"
    target_path = tmp_path / "project-config.toml"
    configured_path.write_text("configured = true\n", encoding="utf-8")
    target_path.write_text("project = true\n", encoding="utf-8")

    assert (
        main(
            [
                "render",
                "--config",
                str(config_path),
                "--client",
                "codex",
                "--apply",
                "--target-path",
                str(target_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert output.endswith("\n")
    assert output.count("\n") == 1
    parsed = json.loads(output)
    assert parsed["client_name"] == "codex"
    assert parsed["target_path"] == str(target_path)
    assert Path(parsed["backup_path"]).parent == tmp_path / "runtime" / "backups" / "codex"
    assert Path(parsed["backup_path"]).name.endswith(f".{target_path.name}")
    assert parsed["dry_run"] is False
    assert configured_path.read_text(encoding="utf-8") == "configured = true\n"
    assert '[mcp_servers."mcp-broker"]' in target_path.read_text(encoding="utf-8")


def test_config_render_cli_outputs_json_for_backup_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker.config_render import main

    config_path = _config_file(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text("original = true\n", encoding="utf-8")

    assert main(
        ["backup", "--config", str(config_path), "--client", "codex", "--label", "20260524T030303Z"]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["client_name"] == "codex"
    assert output["backup_paths"] == [
        str(tmp_path / "runtime" / "backups" / "codex" / "20260524T030303Z.codex.toml")
    ]
    assert target_path.read_text(encoding="utf-8") == "original = true\n"


def test_config_render_apply_enforces_codex_apps_policy(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    app_directory = tmp_path / "codex-cache" / "app-directory" / "directory.json"
    tools_cache = tmp_path / "codex-cache" / "tools" / "tools.json"
    app_directory.parent.mkdir(parents=True)
    tools_cache.parent.mkdir(parents=True)
    app_directory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connectors": [
                    {"id": "connector_github", "name": "GitHub", "isEnabled": True},
                    {"id": "connector_canva", "name": "Canva", "isEnabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    tools_cache.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tools": [
                    {"connector_id": "connector_github", "connector_name": "GitHub", "tool": {}},
                    {"connector_id": "connector_canva", "connector_name": "Canva", "tool": {}},
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path = _config_file(
        tmp_path,
        client_extra={
            "codex_apps_policy": {
                "enabled": True,
                "app_directory_globs": [str(app_directory)],
                "tools_cache_globs": [str(tools_cache)],
                "disable_connectors": [
                    {
                        "id": "connector_github",
                        "name": "GitHub",
                        "reason": "broker owns it",
                    }
                ],
            }
        },
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="codex",
        dry_run=False,
        backup_label="20260524T040404Z",
    )

    assert result.codex_apps_policy_result is not None
    assert result.codex_apps_policy_result.disabled_connectors == 1
    assert result.codex_apps_policy_result.removed_tools == 1
    assert result.codex_apps_policy_result.backups == (
        tmp_path / "runtime" / "backups" / "codex" / "codex-apps" / "20260524T040404Z.directory.json",
        tmp_path / "runtime" / "backups" / "codex" / "codex-apps" / "20260524T040404Z.tools.json",
    )
    assert json.loads(app_directory.read_text(encoding="utf-8"))["connectors"] == [
        {"id": "connector_github", "name": "GitHub", "isEnabled": False},
        {"id": "connector_canva", "name": "Canva", "isEnabled": True},
    ]
    assert [tool["connector_name"] for tool in json.loads(tools_cache.read_text(encoding="utf-8"))["tools"]] == [
        "Canva"
    ]


def test_config_render_dry_run_reports_codex_apps_policy_without_changing_cache(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    app_directory = tmp_path / "app-cache" / "directory.json"
    app_directory.parent.mkdir(parents=True)
    original_cache = {
        "schema_version": 1,
        "connectors": [
            {"id": "connector_docs", "name": "Docs", "isEnabled": True},
            {"id": "connector_design", "name": "Design", "isEnabled": True},
        ],
    }
    app_directory.write_text(json.dumps(original_cache), encoding="utf-8")
    config_path = _config_file(
        tmp_path,
        client_extra={
            "codex_apps_policy": {
                "enabled": True,
                "app_directory_globs": [str(app_directory)],
                "tools_cache_globs": [],
                "disable_connectors": [
                    {
                        "id": "connector_docs",
                        "name": "Docs",
                        "reason": "broker owns this connector",
                    }
                ],
            }
        },
    )

    result = render_client_config(
        BrokerConfig.from_file(config_path),
        client_name="codex",
        dry_run=True,
        backup_label="20260525T030303Z",
    )

    assert result.backup_path is None
    assert result.codex_apps_policy_result is not None
    assert result.codex_apps_policy_result.dry_run is True
    assert result.codex_apps_policy_result.disabled_connectors == 1
    assert json.loads(app_directory.read_text(encoding="utf-8")) == original_cache
    assert not (tmp_path / "runtime" / "backups" / "codex" / "codex-apps").exists()


def test_config_render_app_policy_cli_outputs_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker.config_render import main

    app_directory = tmp_path / "codex-cache" / "app-directory" / "directory.json"
    app_directory.parent.mkdir(parents=True)
    app_directory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connectors": [
                    {"id": "connector_github", "name": "GitHub", "isEnabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path = _config_file(
        tmp_path,
        client_extra={
            "codex_apps_policy": {
                "enabled": True,
                "app_directory_globs": [str(app_directory)],
                "tools_cache_globs": [],
                "disable_connectors": [{"id": "connector_github"}],
            }
        },
    )

    assert (
        main(
            [
                "app-policy",
                "--config",
                str(config_path),
                "--client",
                "codex",
                "--label",
                "20260524T050505Z",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["client_name"] == "codex"
    assert output["codex_apps_policy_result"]["disabled_connectors"] == 1
    assert output["codex_apps_policy_result"]["dry_run"] is True
    assert json.loads(app_directory.read_text(encoding="utf-8"))["connectors"][0]["isEnabled"] is True


def test_config_render_app_policy_cli_apply_writes_cache_and_labeled_backup(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.config_render import main

    app_directory = tmp_path / "app-cache" / "directory.json"
    app_directory.parent.mkdir(parents=True)
    app_directory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connectors": [
                    {"id": "connector_docs", "name": "Docs", "isEnabled": True},
                    {"id": "connector_design", "name": "Design", "isEnabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path = _config_file(
        tmp_path,
        client_extra={
            "codex_apps_policy": {
                "enabled": True,
                "app_directory_globs": [str(app_directory)],
                "tools_cache_globs": [],
                "disable_connectors": [{"id": "connector_docs"}],
            }
        },
    )

    assert (
        main(
            [
                "app-policy",
                "--config",
                str(config_path),
                "--client",
                "codex",
                "--apply",
                "--label",
                "20260525T040404Z",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    result = output["codex_apps_policy_result"]
    assert result["dry_run"] is False
    assert result["disabled_connectors"] == 1
    assert result["backups"] == [
        str(tmp_path / "runtime" / "backups" / "codex" / "codex-apps" / "20260525T040404Z.directory.json")
    ]
    assert json.loads(app_directory.read_text(encoding="utf-8"))["connectors"] == [
        {"id": "connector_docs", "name": "Docs", "isEnabled": False},
        {"id": "connector_design", "name": "Design", "isEnabled": True},
    ]


def test_config_render_app_policy_generates_timestamp_label_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.config_render as config_render

    from mcp_broker.config import BrokerConfig

    app_directory = tmp_path / "app-cache" / "directory.json"
    app_directory.parent.mkdir(parents=True)
    app_directory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connectors": [
                    {"id": "connector_docs", "name": "Docs", "isEnabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path = _config_file(
        tmp_path,
        client_extra={
            "codex_apps_policy": {
                "enabled": True,
                "app_directory_globs": [str(app_directory)],
                "tools_cache_globs": [],
                "disable_connectors": [{"id": "connector_docs"}],
            }
        },
    )
    monkeypatch.setattr(config_render, "_timestamp_label", lambda: "20260525T111213Z")

    result = config_render.apply_client_app_policy(
        BrokerConfig.from_file(config_path),
        client_name="codex",
        dry_run=False,
    )

    assert result.codex_apps_policy_result.backups == (
        tmp_path / "runtime" / "backups" / "codex" / "codex-apps" / "20260525T111213Z.directory.json",
    )
    assert json.loads(app_directory.read_text(encoding="utf-8"))["connectors"] == [
        {"id": "connector_docs", "name": "Docs", "isEnabled": False},
    ]


def test_claude_render_replaces_non_object_json_with_broker_config(tmp_path: Path) -> None:
    import yaml

    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    runtime_root = tmp_path / "runtime"
    target_path = tmp_path / "claude.json"
    target_path.write_text(json.dumps(["not", "a", "config"]), encoding="utf-8")
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "claude": {
                        "format": "claude-json",
                        "config_path": str(target_path),
                        "entry_name": "mcp-broker",
                        "command": "mcp-broker-client",
                        "args": ["--socket-path", str(runtime_root / "sockets" / "broker.sock"), "--profile", "claude"],
                    }
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    render_client_config(BrokerConfig.from_file(config_path), client_name="claude", dry_run=True)

    rendered = json.loads((runtime_root / "renders" / "claude.config.json").read_text(encoding="utf-8"))
    assert rendered == {
        "mcpServers": {
            "mcp-broker": {
                "args": [
                    "--socket-path",
                    str(runtime_root / "sockets" / "broker.sock"),
                    "--profile",
                    "claude",
                ],
                "command": "mcp-broker-client",
            }
        }
    }


def test_json_line_rejects_unknown_object_type() -> None:
    from mcp_broker.config_render import _json_line

    with pytest.raises(TypeError, match="cannot encode object"):
        _json_line(object())


def _config(tmp_path: Path):
    from mcp_broker.config import BrokerConfig

    return BrokerConfig.from_file(_config_file(tmp_path))


def _config_render_parser() -> argparse.ArgumentParser:
    from mcp_broker.config_render import _add_subcommands

    parser = argparse.ArgumentParser(description="contract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_subcommands(subparsers)
    return parser


def _config_file(tmp_path: Path, client_extra: dict[str, object] | None = None) -> Path:
    import yaml

    runtime_root = tmp_path / "runtime"
    path = tmp_path / "broker.yaml"
    codex_client = {
        "format": "codex-toml",
        "config_path": str(tmp_path / "codex.toml"),
        "entry_name": "mcp-broker",
        "command": "mcp-broker-client",
    }
    if client_extra:
        codex_client.update(client_extra)
    path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "codex": codex_client
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path
