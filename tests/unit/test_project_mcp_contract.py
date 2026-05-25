from pathlib import Path
import json
import re

import pytest
import yaml


pytestmark = pytest.mark.unit


def _write_broker_config(path: Path) -> None:
    path.write_text(
        """
schema_version: 1
runtime:
  root: /tmp/mcp-broker-test
profiles:
  codex:
    max_tools: 80
    compact_tools_enabled: true
  claude:
    max_tools: 80
    compact_tools_enabled: true
  manual-test:
    max_tools: 200
    compact_tools_enabled: false
upstreams:
  covered-tool:
    command: covered-tool
    tool_prefix: covered-tool
    profiles:
      - codex
      - claude
  covered-no-prefix:
    command: covered-no-prefix
    profiles:
      - codex
      - claude
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_project_mcp(path: Path, servers: dict[str, object]) -> None:
    path.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")


def test_project_mcp_audit_reports_covered_and_missing_servers(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(
        project / ".mcp.json",
        {
            "covered-tool": {"command": "covered-tool"},
            "missing-tool": {"command": "missing-tool", "args": ["--serve"]},
        },
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=False,
        apply=False,
        profiles=["codex", "claude"],
    )

    assert report.apply is False
    assert report.files_scanned == 1
    assert report.covered_servers == ["covered-tool"]
    assert report.missing_servers == ["missing-tool"]
    assert report.files_changed == []
    assert report.files_blocked == [project / ".mcp.json"]


def test_project_mcp_apply_empties_only_fully_covered_files_and_creates_backup(
    tmp_path: Path,
) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    backup_root = tmp_path / "backups"
    covered_project = tmp_path / "covered"
    blocked_project = tmp_path / "blocked"
    covered_project.mkdir()
    blocked_project.mkdir()
    covered_file = covered_project / ".mcp.json"
    blocked_file = blocked_project / ".mcp.json"
    _write_project_mcp(covered_file, {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(blocked_file, {"missing-tool": {"command": "missing-tool"}})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=backup_root,
        import_missing=False,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert report.files_changed == [covered_file]
    assert report.files_blocked == [blocked_file]
    assert json.loads(covered_file.read_text(encoding="utf-8")) == {"mcpServers": {}}
    assert json.loads(blocked_file.read_text(encoding="utf-8"))["mcpServers"] == {
        "missing-tool": {"command": "missing-tool"}
    }
    assert len(report.backups) == 1
    assert report.backups[0].exists()
    assert "covered-tool" in report.backups[0].read_text(encoding="utf-8")


def test_project_mcp_dry_run_fully_covered_file_changes_nothing(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    project_file = project / ".mcp.json"
    _write_project_mcp(project_file, {"covered-tool": {"command": "covered-tool"}})
    before = project_file.read_text(encoding="utf-8")

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=tmp_path / "backups",
        import_missing=False,
        apply=False,
        profiles=["codex", "claude"],
    )

    assert report.files_changed == []
    assert report.files_blocked == []
    assert report.backups == []
    assert project_file.read_text(encoding="utf-8") == before


def test_project_mcp_imports_missing_stdio_and_http_servers_before_emptying(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    mcp_file = project / ".mcp.json"
    _write_project_mcp(
        mcp_file,
        {
            "local-tool": {
                "command": "local-tool",
                "args": ["serve"],
                "env": {"LOCAL_TOKEN": "${LOCAL_TOKEN}"},
            },
            "remote-tool": {
                "type": "http",
                "url": "https://example.invalid/mcp",
                "headers": {"Authorization": "Bearer ${REMOTE_TOKEN}"},
            },
        },
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=True,
        profiles=["codex", "claude"],
    )

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert sorted(report.imported_servers) == ["local-tool", "remote-tool"]
    assert json.loads(mcp_file.read_text(encoding="utf-8")) == {"mcpServers": {}}
    assert loaded["upstreams"]["local-tool"]["command"] == "local-tool"
    assert loaded["upstreams"]["local-tool"]["args"] == ["serve"]
    assert loaded["upstreams"]["local-tool"]["env"] == {"LOCAL_TOKEN": "LOCAL_TOKEN"}
    assert loaded["upstreams"]["remote-tool"]["transport"] == "http"
    assert loaded["upstreams"]["remote-tool"]["command"] == "https://example.invalid/mcp"
    assert loaded["upstreams"]["remote-tool"]["env"] == {
        "AUTHORIZATION": "REMOTE_TOKEN",
    }
    BrokerConfig.from_file(config_path)


def test_project_mcp_imports_http_server_without_headers(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(
        project / ".mcp.json",
        {"remote-tool": {"url": "https://example.invalid/mcp"}},
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=True,
        profiles=["codex"],
    )

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert report.imported_servers == ["remote-tool"]
    assert "env" not in loaded["upstreams"]["remote-tool"]


def test_project_mcp_refuses_literal_secret_import(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    mcp_file = project / ".mcp.json"
    _write_project_mcp(
        mcp_file,
        {"bad-secret": {"command": "bad-secret", "env": {"TOKEN": "literal-value"}}},
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert report.files_changed == []
    assert report.files_blocked == [mcp_file]
    assert report.import_errors == {
        "bad-secret": "env.TOKEN must reference an environment variable"
    }
    assert json.loads(mcp_file.read_text(encoding="utf-8"))["mcpServers"]["bad-secret"]


def test_project_mcp_main_outputs_json_for_dry_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.project_mcp import main

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--root",
                str(tmp_path),
                "--backup-root",
                str(tmp_path / "backups"),
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out)["files_scanned"] == 0


def test_project_mcp_main_defaults_profiles_and_returns_blocked_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.project_mcp import main

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(project / ".mcp.json", {"missing-tool": {"command": "missing-tool"}})

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--root",
                str(project),
                "--backup-root",
                str(tmp_path / "backups"),
            ]
        )
        == 2
    )

    output = json.loads(capsys.readouterr().out)
    assert output["files_blocked"] == [str(project / ".mcp.json")]


def test_project_mcp_main_accepts_explicit_profile(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.project_mcp import main

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(project / ".mcp.json", {"local-tool": {"command": "local-tool"}})

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--root",
                str(project),
                "--backup-root",
                str(tmp_path / "backups"),
                "--profile",
                "manual-test",
                "--import-missing",
                "--apply",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["imported_servers"] == ["local-tool"]
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["upstreams"]["local-tool"]["profiles"] == ["manual-test"]


def test_project_mcp_scan_skips_missing_backup_and_dependency_paths(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    dependency_dir = tmp_path / "node_modules" / "package"
    dependency_dir.mkdir(parents=True)
    git_dir = tmp_path / ".git" / "fixtures"
    git_dir.mkdir(parents=True)
    empty_project = tmp_path / "empty"
    empty_project.mkdir()
    _write_project_mcp(backup_root / ".mcp.json", {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(dependency_dir / ".mcp.json", {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(git_dir / ".mcp.json", {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(empty_project / ".mcp.json", {})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path / "does-not-exist", tmp_path],
        backup_root=backup_root,
        import_missing=False,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert report.files_scanned == 1
    assert report.files_changed == []
    assert report.files_blocked == []
    assert report.backups == []


def test_project_mcp_migrates_claude_project_state_entries(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    sibling_project = tmp_path / "sibling"
    other_project = tmp_path / "other"
    outside_project = tmp_path.parent / "outside-project"
    project.mkdir()
    sibling_project.mkdir()
    other_project.mkdir()
    outside_project.mkdir(exist_ok=True)
    claude_config = tmp_path / "claude.json"
    claude_config.write_text(
        json.dumps(
            {
                "projects": {
                    str(project): {
                        "mcpServers": {"covered-tool": {"command": "covered-tool"}},
                        "otherSetting": True,
                    },
                    str(sibling_project): {
                        "mcpServers": {"covered-tool": {"command": "covered-tool"}},
                    },
                    str(other_project): {
                        "mcpServers": {"covered-tool": {"command": "covered-tool"}},
                    },
                    str(outside_project): {
                        "mcpServers": {"covered-tool": {"command": "covered-tool"}},
                    },
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=False,
        apply=True,
        profiles=["codex", "claude"],
        claude_config_path=claude_config,
    )

    loaded = json.loads(claude_config.read_text(encoding="utf-8"))
    assert report.files_scanned == 3
    assert report.files_changed == [claude_config, claude_config, claude_config]
    assert len(report.backups) == 1
    assert loaded["projects"][str(project)]["mcpServers"] == {}
    assert loaded["projects"][str(project)]["otherSetting"] is True
    assert loaded["projects"][str(sibling_project)]["mcpServers"] == {}
    assert loaded["projects"][str(other_project)]["mcpServers"] == {}
    assert loaded["projects"][str(outside_project)]["mcpServers"] == {
        "covered-tool": {"command": "covered-tool"}
    }


def test_project_mcp_imports_missing_claude_project_state_entry(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    claude_config = tmp_path / "claude.json"
    claude_config.write_text(
        json.dumps(
            {
                "projects": {
                    str(project): {
                        "mcpServers": {"local-tool": {"command": "local-tool"}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=True,
        profiles=["claude"],
        claude_config_path=claude_config,
    )

    assert report.imported_servers == ["local-tool"]
    assert json.loads(claude_config.read_text(encoding="utf-8"))["projects"][str(project)]["mcpServers"] == {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert loaded["upstreams"]["local-tool"]["profiles"] == ["claude"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must contain a JSON object"),
        ({"projects": []}, "projects must be an object"),
        ({"projects": {"__PROJECT__": []}}, "must be an object"),
        ({"projects": {"__PROJECT__": {"mcpServers": []}}}, "mcpServers must be an object"),
    ],
)
def test_project_mcp_rejects_invalid_claude_config_shape(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    claude_config = tmp_path / "claude.json"
    materialized_payload = json.loads(json.dumps(payload).replace("__PROJECT__", str(project)))
    claude_config.write_text(json.dumps(materialized_payload), encoding="utf-8")

    with pytest.raises(ValueError, match=re.escape(message)):
        audit_project_mcp_files(
            config_path=config_path,
            roots=[tmp_path],
            backup_root=tmp_path / "backups",
            import_missing=False,
            apply=False,
            profiles=["codex", "claude"],
            claude_config_path=claude_config,
        )


def test_project_mcp_ignores_missing_claude_config_and_missing_project_path(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import _load_claude_project_entries, _path_matches_roots

    assert _load_claude_project_entries(None, [tmp_path]) == []
    assert _load_claude_project_entries(tmp_path / "missing.json", [tmp_path]) == []
    assert _path_matches_roots(tmp_path / "missing-project", [tmp_path]) is False


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"projects": []},
        {"projects": {"missing": []}},
    ],
)
def test_project_mcp_empty_claude_writer_revalidates_current_file(
    tmp_path: Path,
    payload: object,
) -> None:
    from mcp_broker.project_mcp import _ProjectMcpFile, _write_empty_mcp_servers

    claude_config = tmp_path / "claude.json"
    claude_config.write_text(json.dumps(payload), encoding="utf-8")
    project_file = _ProjectMcpFile(
        path=claude_config,
        data={},
        servers={"covered-tool": {"command": "covered-tool"}},
        claude_project_path="missing",
    )

    with pytest.raises(ValueError):
        _write_empty_mcp_servers(project_file)


def test_project_mcp_covered_names_include_upstreams_without_tool_prefix(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.project_mcp import _covered_server_names

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": str(tmp_path / "runtime")}),
        broker=BrokerSettings(),
        profiles={},
        upstreams={
            "covered-no-prefix": UpstreamConfig(
                name="covered-no-prefix",
                command="covered-no-prefix",
                tool_prefix=None,
            )
        },
    )

    assert _covered_server_names(config) == {"covered-no-prefix"}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must contain a JSON object"),
        ({"mcpServers": []}, "mcpServers must be an object"),
    ],
)
def test_project_mcp_rejects_invalid_project_file_shape(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        audit_project_mcp_files(
            config_path=config_path,
            roots=[project],
            backup_root=tmp_path / "backups",
            import_missing=False,
            apply=False,
            profiles=["codex", "claude"],
        )


@pytest.mark.parametrize(
    ("server_config", "message"),
    [
        ([], "server config must be an object"),
        ({"args": []}, "stdio server requires command"),
        ({"command": "bad", "args": "--serve"}, "args must be a list"),
        ({"command": "bad", "env": []}, "env must be an object"),
        ({"command": "bad", "env": {"BAD-NAME": "GOOD_NAME"}}, "env keys must be environment variable names"),
        ({"command": "bad", "env": {"TOKEN": ""}}, "env.TOKEN must reference an environment variable"),
        ({"type": "sse"}, "http server requires url"),
        ({"type": "http", "url": "https://example.invalid/mcp", "headers": []}, "headers must be an object"),
        (
            {
                "type": "http",
                "url": "https://example.invalid/mcp",
                "headers": {"Authorization": "Bearer literal"},
            },
            "headers.Authorization must reference an environment variable",
        ),
    ],
)
def test_project_mcp_import_reports_invalid_server_shapes(
    tmp_path: Path,
    server_config: object,
    message: str,
) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(project / ".mcp.json", {"bad-tool": server_config})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert report.files_changed == []
    assert report.files_blocked == [project / ".mcp.json"]
    assert report.import_errors == {"bad-tool": message}


def test_project_mcp_header_parser_rejects_programmatic_non_string_keys() -> None:
    from mcp_broker.project_mcp import _parse_header_mapping

    assert _parse_header_mapping({42: "TOKEN"}) == ({}, "header keys must be strings")


def test_project_mcp_import_extracts_bare_environment_source(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(
        project / ".mcp.json",
        {"local-tool": {"command": "local-tool", "env": {"TOKEN": "SOURCE_TOKEN"}}},
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=True,
        profiles=["manual-test"],
    )

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert report.imported_servers == ["local-tool"]
    assert loaded["upstreams"]["local-tool"]["profiles"] == ["manual-test"]
    assert loaded["upstreams"]["local-tool"]["env"] == {"TOKEN": "SOURCE_TOKEN"}


def test_project_mcp_import_appends_upstreams_when_config_has_no_upstreams(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        """
schema_version: 1
runtime:
  root: /tmp/mcp-broker-test
profiles:
  codex:
    max_tools: 80
    compact_tools_enabled: true
""".lstrip(),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(project / ".mcp.json", {"local-tool": {"command": "local-tool"}})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=True,
        profiles=["codex"],
    )

    assert report.files_changed == [project / ".mcp.json"]
    assert "upstreams:\n  local-tool:" in config_path.read_text(encoding="utf-8")
    BrokerConfig.from_file(config_path)


def test_project_mcp_insert_under_upstreams_before_next_top_level_without_newline() -> None:
    from mcp_broker.project_mcp import _insert_under_upstreams

    config_text = "schema_version: 1\nupstreams:\nprofiles:"

    assert _insert_under_upstreams(config_text, "  local-tool:\n    command: local-tool\n") == (
        "schema_version: 1\n"
        "upstreams:\n"
        "  local-tool:\n"
        "    command: local-tool\n"
        "profiles:"
    )


def test_project_mcp_insert_under_terminal_upstreams_line_adds_newline() -> None:
    from mcp_broker.project_mcp import _insert_under_upstreams

    config_text = "schema_version: 1\nupstreams:"

    assert _insert_under_upstreams(config_text, "  local-tool:\n    command: local-tool\n") == (
        "schema_version: 1\n"
        "upstreams:\n"
        "  local-tool:\n"
        "    command: local-tool\n"
    )


def test_project_mcp_import_rolls_back_when_broker_validation_fails(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import _append_missing_upstreams

    config_path = tmp_path / "broker.yaml"
    original = """
schema_version: 1
runtime:
  root: /tmp/mcp-broker-test
profiles:
  codex:
    max_tools: 80
    compact_tools_enabled: true
upstreams:
""".lstrip()
    config_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError):
        _append_missing_upstreams(
            config_path,
            {
                "local-tool": {
                    "enabled": True,
                    "mode": "shared",
                    "profiles": ["missing-profile"],
                    "transport": "stdio",
                    "command": "local-tool",
                }
            },
        )

    assert config_path.read_text(encoding="utf-8") == original
