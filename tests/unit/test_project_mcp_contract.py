from datetime import UTC
from pathlib import Path
import json
import re

import pytest
import yaml


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


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
    backup_root = tmp_path / "00-backups"
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


def test_project_mcp_apply_creates_nested_backup_root(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    covered_file = project / ".mcp.json"
    backup_root = tmp_path / "nested" / "backup" / "root"
    _write_project_mcp(covered_file, {"covered-tool": {"command": "covered-tool"}})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=backup_root,
        import_missing=False,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert len(report.backups) == 1
    assert report.backups[0].parent == backup_root
    assert report.backups[0].read_text(encoding="utf-8") == (
        '{\n  "mcpServers": {\n    "covered-tool": {\n      "command": "covered-tool"\n    }\n  }\n}\n'
    )


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
    assert loaded["upstreams"]["local-tool"]["tool_prefix"] == "local-tool"
    assert loaded["upstreams"]["local-tool"]["state_dir"] == "upstreams/local-tool"
    assert (
        loaded["upstreams"]["local-tool"]["purpose"]
        == "Imported from project-local .mcp.json entry local-tool."
    )
    assert loaded["upstreams"]["remote-tool"]["transport"] == "http"
    assert loaded["upstreams"]["remote-tool"]["command"] == "https://example.invalid/mcp"
    assert loaded["upstreams"]["remote-tool"]["env"] == {
        "AUTHORIZATION": "REMOTE_TOKEN",
    }
    assert loaded["upstreams"]["remote-tool"]["tool_prefix"] == "remote-tool"
    assert loaded["upstreams"]["remote-tool"]["state_dir"] == "upstreams/remote-tool"
    assert (
        loaded["upstreams"]["remote-tool"]["purpose"]
        == "Imported from project-local .mcp.json entry remote-tool."
    )
    BrokerConfig.from_file(config_path)


def test_project_mcp_import_keeps_first_definition_for_duplicate_missing_server(
    tmp_path: Path,
) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    first_project = tmp_path / "a-first-project"
    second_project = tmp_path / "b-second-project"
    first_project.mkdir()
    second_project.mkdir()
    _write_project_mcp(
        first_project / ".mcp.json",
        {"local-tool": {"command": "first-command", "args": ["first"]}},
    )
    _write_project_mcp(
        second_project / ".mcp.json",
        {"local-tool": {"command": "second-command", "args": ["second"]}},
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
    assert report.imported_servers == ["local-tool"]
    assert loaded["upstreams"]["local-tool"]["command"] == "first-command"
    assert loaded["upstreams"]["local-tool"]["args"] == ["first"]


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


def test_project_mcp_main_outputs_sorted_json_keys(
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

    output = capsys.readouterr().out
    assert output.index('"backups"') < output.index('"import_missing"')


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


def test_project_mcp_report_preserves_import_missing_flag(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)

    dry_report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=False,
        apply=False,
        profiles=["codex", "claude"],
    )
    import_report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=True,
        apply=False,
        profiles=["codex", "claude"],
    )

    assert dry_report.import_missing is False
    assert dry_report.to_jsonable()["import_missing"] is False
    assert import_report.import_missing is True
    assert import_report.to_jsonable()["import_missing"] is True


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


def test_project_mcp_main_passes_claude_config_to_audit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.project_mcp import main

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

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--root",
                str(project),
                "--backup-root",
                str(tmp_path / "backups"),
                "--claude-config",
                str(claude_config),
                "--import-missing",
                "--apply",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["files_scanned"] == 1
    assert output["imported_servers"] == ["local-tool"]
    assert json.loads(claude_config.read_text(encoding="utf-8"))["projects"][str(project)]["mcpServers"] == {}


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
    venv_dir = tmp_path / "venv-mcp-broker" / "fixtures"
    venv_dir.mkdir(parents=True)
    empty_project = tmp_path / "10-empty"
    empty_project.mkdir()
    covered_project = tmp_path / "20-covered"
    covered_project.mkdir()
    _write_project_mcp(backup_root / ".mcp.json", {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(dependency_dir / ".mcp.json", {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(git_dir / ".mcp.json", {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(venv_dir / ".mcp.json", {"covered-tool": {"command": "covered-tool"}})
    _write_project_mcp(empty_project / ".mcp.json", {})
    covered_file = covered_project / ".mcp.json"
    _write_project_mcp(covered_file, {"covered-tool": {"command": "covered-tool"}})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path / "does-not-exist", tmp_path],
        backup_root=backup_root,
        import_missing=False,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert report.files_scanned == 2
    assert report.files_changed == [covered_file]
    assert report.files_blocked == []
    assert len(report.backups) == 1


def test_project_mcp_file_discovery_continues_after_ignored_paths(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import _find_project_mcp_files

    backup_dir = tmp_path / ".backup" / "snapshot"
    git_dir = tmp_path / ".git" / "fixtures"
    valid_dir = tmp_path / "zz-valid-project"
    backup_dir.mkdir(parents=True)
    git_dir.mkdir(parents=True)
    valid_dir.mkdir()
    backup_file = backup_dir / ".mcp.json"
    ignored_file = git_dir / ".mcp.json"
    valid_file = valid_dir / ".mcp.json"
    _write_project_mcp(backup_file, {"backup-tool": {"command": "backup-tool"}})
    _write_project_mcp(ignored_file, {"ignored-tool": {"command": "ignored-tool"}})
    _write_project_mcp(valid_file, {"covered-tool": {"command": "covered-tool"}})

    assert _find_project_mcp_files([tmp_path], tmp_path / ".backup") == [valid_file]


def test_project_mcp_empty_file_does_not_stop_later_file_changes(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    empty_project = tmp_path / "10-empty"
    covered_project = tmp_path / "20-covered"
    empty_project.mkdir()
    covered_project.mkdir()
    empty_file = empty_project / ".mcp.json"
    covered_file = covered_project / ".mcp.json"
    _write_project_mcp(empty_file, {})
    _write_project_mcp(covered_file, {"covered-tool": {"command": "covered-tool"}})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=False,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert report.files_scanned == 2
    assert report.files_changed == [covered_file]
    assert report.files_blocked == []
    assert json.loads(empty_file.read_text(encoding="utf-8")) == {"mcpServers": {}}
    assert json.loads(covered_file.read_text(encoding="utf-8")) == {"mcpServers": {}}


def test_project_mcp_missing_mcp_servers_field_is_treated_as_empty(tmp_path: Path) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    covered_project = tmp_path / "covered"
    project.mkdir()
    covered_project.mkdir()
    missing_field_file = project / ".mcp.json"
    covered_file = covered_project / ".mcp.json"
    missing_field_file.write_text(json.dumps({"otherSetting": True}) + "\n", encoding="utf-8")
    _write_project_mcp(covered_file, {"covered-tool": {"command": "covered-tool"}})

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[tmp_path],
        backup_root=tmp_path / "backups",
        import_missing=False,
        apply=True,
        profiles=["codex", "claude"],
    )

    assert report.files_scanned == 2
    assert report.files_changed == [covered_file]
    assert report.files_blocked == []
    assert json.loads(missing_field_file.read_text(encoding="utf-8")) == {"otherSetting": True}


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


def test_project_mcp_nonmatching_claude_project_does_not_stop_later_matching_entry(
    tmp_path: Path,
) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    outside_project = tmp_path.parent / "outside-project"
    project.mkdir()
    outside_project.mkdir(exist_ok=True)
    claude_config = tmp_path / "claude.json"
    claude_config.write_text(
        json.dumps(
            {
                "projects": {
                    str(outside_project): {
                        "mcpServers": {"outside-tool": {"command": "outside-tool"}},
                    },
                    str(project): {
                        "mcpServers": {"covered-tool": {"command": "covered-tool"}},
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    report = audit_project_mcp_files(
        config_path=config_path,
        roots=[project],
        backup_root=tmp_path / "backups",
        import_missing=False,
        apply=True,
        profiles=["claude"],
        claude_config_path=claude_config,
    )

    loaded = json.loads(claude_config.read_text(encoding="utf-8"))
    assert report.files_scanned == 1
    assert report.files_changed == [claude_config]
    assert loaded["projects"][str(project)]["mcpServers"] == {}
    assert loaded["projects"][str(outside_project)]["mcpServers"] == {
        "outside-tool": {"command": "outside-tool"}
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

    missing_projects_config = tmp_path / "empty-claude.json"
    missing_projects_config.write_text("{}", encoding="utf-8")
    missing_servers_config = tmp_path / "missing-servers-claude.json"
    missing_servers_config.write_text(
        json.dumps({"projects": {str(tmp_path): {"otherSetting": True}}}),
        encoding="utf-8",
    )

    assert _load_claude_project_entries(None, [tmp_path]) == []
    assert _load_claude_project_entries(tmp_path / "missing.json", [tmp_path]) == []
    assert _load_claude_project_entries(missing_projects_config, [tmp_path]) == []
    entries = _load_claude_project_entries(missing_servers_config, [tmp_path])
    assert len(entries) == 1
    assert entries[0].servers == {}
    assert entries[0].data == {"projects": {str(tmp_path): {"otherSetting": True}}}
    assert _path_matches_roots(tmp_path / "missing-project", [tmp_path]) is False


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must contain a JSON object"),
        ({}, "projects.missing must be an object"),
        ({"projects": []}, "projects must be an object"),
        ({"projects": {"missing": []}}, "projects.missing must be an object"),
    ],
)
def test_project_mcp_empty_claude_writer_revalidates_current_file(
    tmp_path: Path,
    payload: object,
    message: str,
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

    with pytest.raises(ValueError, match=re.escape(message)):
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


def test_project_mcp_covered_names_include_tool_prefix_aliases(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.project_mcp import _covered_server_names

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": str(tmp_path / "runtime")}),
        broker=BrokerSettings(),
        profiles={},
        upstreams={
            "central-upstream-name": UpstreamConfig(
                name="central-upstream-name",
                command="tool",
                tool_prefix="project-local-name",
            )
        },
    )

    assert _covered_server_names(config) == {
        "central-upstream-name",
        "project-local-name",
    }


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
        ({"command": ["bad"]}, "stdio server requires command"),
        ({"command": "bad", "args": "--serve"}, "args must be a list"),
        ({"command": "bad", "env": []}, "env must be an object"),
        ({"command": "bad", "env": {"BAD-NAME": "GOOD_NAME"}}, "env keys must be environment variable names"),
        ({"command": "bad", "env": {"TOKEN": ""}}, "env.TOKEN must reference an environment variable"),
        ({"type": "http"}, "http server requires url"),
        ({"type": "sse"}, "http server requires url"),
        ({"type": "http", "url": ["bad"]}, "http server requires url"),
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
    assert report.missing_servers == ["bad-tool"]
    assert report.import_errors == {"bad-tool": message}


def test_project_mcp_import_reports_later_invalid_servers_after_first_invalid(
    tmp_path: Path,
) -> None:
    from mcp_broker.project_mcp import audit_project_mcp_files

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project = tmp_path / "project"
    project.mkdir()
    _write_project_mcp(
        project / ".mcp.json",
        {
            "bad-stdio": {"args": []},
            "bad-http": {"type": "http"},
        },
    )

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
    assert report.missing_servers == ["bad-http", "bad-stdio"]
    assert report.import_errors == {
        "bad-http": "http server requires url",
        "bad-stdio": "stdio server requires command",
    }


def test_project_mcp_header_parser_rejects_programmatic_non_string_keys() -> None:
    from mcp_broker.project_mcp import _parse_header_mapping

    assert _parse_header_mapping({42: "TOKEN"}) == ({}, "header keys must be strings")


def test_project_mcp_env_parser_accepts_common_env_reference_forms() -> None:
    from mcp_broker.project_mcp import _parse_env_mapping

    parsed, error = _parse_env_mapping(
        {
            "TOKEN": "SOURCE_TOKEN",
            "ALT_TOKEN": "$ALT_SOURCE_TOKEN",
            "BRACED_TOKEN": "${BRACED_SOURCE_TOKEN}",
            "AUTH_HEADER": "Bearer ${AUTH_SOURCE_TOKEN}",
        }
    )

    assert error is None
    assert parsed == {
        "TOKEN": "SOURCE_TOKEN",
        "ALT_TOKEN": "ALT_SOURCE_TOKEN",
        "BRACED_TOKEN": "BRACED_SOURCE_TOKEN",
        "AUTH_HEADER": "AUTH_SOURCE_TOKEN",
    }


@pytest.mark.parametrize(
    ("env_value", "message"),
    [
        ("literal-secret-value", "env.TOKEN must reference an environment variable"),
        ("Bearer literal-secret-value", "env.TOKEN must reference an environment variable"),
        ("", "env.TOKEN must reference an environment variable"),
        (42, "env.TOKEN must reference an environment variable"),
    ],
)
def test_project_mcp_env_parser_rejects_literal_values(
    env_value: object,
    message: str,
) -> None:
    from mcp_broker.project_mcp import _parse_env_mapping

    assert _parse_env_mapping({"TOKEN": env_value}) == ({}, message)


def test_project_mcp_env_parser_rejects_invalid_target_names() -> None:
    from mcp_broker.project_mcp import _parse_env_mapping

    assert _parse_env_mapping({"not-valid-name": "SOURCE_TOKEN"}) == (
        {},
        "env keys must be environment variable names",
    )


def test_project_mcp_header_parser_normalizes_header_names() -> None:
    from mcp_broker.project_mcp import _parse_header_mapping

    parsed, error = _parse_header_mapping(
        {
            "Authorization": "AUTH_TOKEN",
            "x-api-key": "${API_KEY_TOKEN}",
            "X-Trace-Id": "TRACE_TOKEN",
            "!!!": "$FALLBACK_HEADER_TOKEN",
        }
    )

    assert error is None
    assert parsed == {
        "AUTHORIZATION": "AUTH_TOKEN",
        "X_API_KEY": "API_KEY_TOKEN",
        "X_TRACE_ID": "TRACE_TOKEN",
        "HEADER": "FALLBACK_HEADER_TOKEN",
    }


def test_project_mcp_header_parser_rejects_literal_header_values() -> None:
    from mcp_broker.project_mcp import _parse_header_mapping

    assert _parse_header_mapping({"Authorization": "Bearer literal-secret"}) == (
        {},
        "headers.Authorization must reference an environment variable",
    )


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


def test_project_mcp_insert_under_upstreams_preserves_comments_blanks_and_existing_entries() -> None:
    from mcp_broker.project_mcp import _insert_under_upstreams

    addition = "  local-tool:\n    command: local-tool\n"
    config_text = (
        "schema_version: 1\n"
        "upstreams:\n"
        "  existing-tool:\n"
        "    command: existing-tool\n"
        "# retained comment\n"
        "profiles:\n"
    )

    assert _insert_under_upstreams(config_text, addition) == (
        "schema_version: 1\n"
        "upstreams:\n"
        "  existing-tool:\n"
        "    command: existing-tool\n"
        "# retained comment\n"
        "  local-tool:\n"
        "    command: local-tool\n"
        "profiles:\n"
    )
    assert _insert_under_upstreams("upstreams:\n\nprofiles:\n", addition) == (
        "upstreams:\n"
        "\n"
        "  local-tool:\n"
        "    command: local-tool\n"
        "profiles:\n"
    )


def test_project_mcp_insert_under_missing_upstreams_preserves_trailing_newline() -> None:
    from mcp_broker.project_mcp import _insert_under_upstreams

    assert _insert_under_upstreams("schema_version: 1\n", "  local-tool: {}\n") == (
        "schema_version: 1\n"
        "upstreams:\n"
        "  local-tool: {}\n"
    )


def test_project_mcp_insert_under_bare_upstreams_line_and_addition_without_newline() -> None:
    from mcp_broker.project_mcp import _insert_under_upstreams

    assert _insert_under_upstreams("upstreams:", "  local-tool: {}") == (
        "upstreams:\n"
        "  local-tool: {}\n"
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


def test_project_mcp_parser_preserves_public_option_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.project_mcp import _parse_args

    parsed = _parse_args(
        [
            "--config",
            str(tmp_path / "broker.yaml"),
            "--root",
            str(tmp_path / "one"),
            "--root",
            str(tmp_path / "two"),
            "--backup-root",
            str(tmp_path / "backups"),
            "--claude-config",
            str(tmp_path / "claude.json"),
            "--profile",
            "codex",
            "--profile",
            "claude",
            "--import-missing",
            "--apply",
        ]
    )

    assert parsed.config == tmp_path / "broker.yaml"
    assert parsed.root == [tmp_path / "one", tmp_path / "two"]
    assert parsed.backup_root == tmp_path / "backups"
    assert parsed.claude_config == tmp_path / "claude.json"
    assert parsed.profile == ["codex", "claude"]
    assert parsed.import_missing is True
    assert parsed.apply is True

    defaults = _parse_args(
        [
            "--config",
            str(tmp_path / "broker.yaml"),
            "--root",
            str(tmp_path),
            "--backup-root",
            str(tmp_path / "backups"),
        ]
    )
    assert defaults.profile == ["codex", "claude"]
    assert defaults.import_missing is False
    assert defaults.apply is False

    with pytest.raises(SystemExit) as help_exit:
        _parse_args(["--help"])
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    assert "XX" not in help_text
    for fragment in [
        "Audit and migrate project-local .mcp.json files",
        "Broker YAML config",
        "Root to scan recursively; repeat for multiple roots",
        "Backup directory",
        "Claude JSON config with per-project MCP entries",
        "Broker profile for imported upstreams",
        "Append missing entries to broker config",
        "Write backups, imports, and empty .mcp.json files",
    ]:
        assert fragment in help_text


@pytest.mark.parametrize(
    ("args", "missing_option"),
    [
        (["--root", "__ROOT__", "--backup-root", "__BACKUP__"], "--config"),
        (["--config", "__CONFIG__", "--backup-root", "__BACKUP__"], "--root"),
        (["--config", "__CONFIG__", "--root", "__ROOT__"], "--backup-root"),
    ],
)
def test_project_mcp_parser_requires_config_root_and_backup_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    missing_option: str,
) -> None:
    from mcp_broker.project_mcp import _parse_args

    materialized = [
        arg.replace("__CONFIG__", str(tmp_path / "broker.yaml"))
        .replace("__ROOT__", str(tmp_path))
        .replace("__BACKUP__", str(tmp_path / "backups"))
        for arg in args
    ]

    with pytest.raises(SystemExit) as exc:
        _parse_args(materialized)

    assert exc.value.code == 2
    assert missing_option in capsys.readouterr().err


def test_project_mcp_migration_helpers_preserve_file_format_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import project_mcp

    assert project_mcp._is_http_server({"type": "HTTP"}) is True
    assert project_mcp._is_http_server({"type": "sse"}) is True
    assert project_mcp._is_http_server({"url": "https://example.invalid/mcp"}) is True
    assert project_mcp._is_http_server({"type": "stdio"}) is False
    assert project_mcp._is_http_server({"type": None}) is False
    assert project_mcp._is_http_server({}) is False
    assert project_mcp._header_env_name("!!!") == "HEADER"
    assert project_mcp._header_env_name("x-api-key") == "X_API_KEY"
    assert project_mcp._base_import("local-tool", ("codex", "claude")) == {
        "enabled": True,
        "mode": "shared",
        "purpose": "Imported from project-local .mcp.json entry local-tool.",
        "tags": ["project-import"],
        "tool_prefix": "local-tool",
        "state_dir": "upstreams/local-tool",
        "profiles": ["codex", "claude"],
    }
    assert project_mcp._yaml_upstream_addition(
        {"b-tool": {"command": "b"}, "a-tool": {"command": "a"}}
    ) == "  b-tool:\n    command: b\n  a-tool:\n    command: a\n"
    assert project_mcp._insert_under_upstreams("schema_version: 1", "  local-tool: {}\n") == (
        "schema_version: 1\nupstreams:\n  local-tool: {}\n"
    )

    project_file = tmp_path / "Mixed Project" / ".mcp.json"
    project_file.parent.mkdir()
    _write_project_mcp(project_file, {"covered-tool": {"command": "covered-tool"}})
    backup_root = tmp_path / "backup-root"
    seen_timezone = []

    def fixed_now(timezone: object) -> object:
        seen_timezone.append(timezone)
        return type("FixedNow", (), {"strftime": lambda _self, fmt: f"{fmt}:fixed"})()

    fixed_datetime = type(
        "FixedDateTime",
        (),
        {"now": staticmethod(fixed_now)},
    )
    monkeypatch.setattr(project_mcp, "datetime", fixed_datetime)

    backup_path = project_mcp._backup_file(project_file, backup_root)

    assert seen_timezone == [UTC]
    assert backup_path.parent == backup_root
    assert backup_path.name.startswith("%Y%m%dT%H%M%SZ:fixed.")
    assert "Mixed__Project__.mcp.json" in backup_path.name
    assert backup_path.read_text(encoding="utf-8") == project_file.read_text(encoding="utf-8")

    mcp_state = project_mcp._ProjectMcpFile(
        path=project_file,
        data={"z": True, "mcpServers": {"covered-tool": {"command": "covered-tool"}}},
        servers={"covered-tool": {"command": "covered-tool"}},
    )
    project_mcp._write_empty_mcp_servers(mcp_state)
    assert project_file.read_text(encoding="utf-8") == (
        '{\n  "mcpServers": {},\n  "z": true\n}\n'
    )


def test_project_mcp_yaml_dump_contract_uses_insertion_order_and_block_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import project_mcp

    calls: list[dict[str, object]] = []

    def fake_safe_dump(value: object, **kwargs: object) -> str:
        calls.append({"value": value, **kwargs})
        return "b-tool:\n  command: b\n"

    monkeypatch.setattr(project_mcp.yaml, "safe_dump", fake_safe_dump)

    assert project_mcp._yaml_upstream_addition({"b-tool": {"command": "b"}}) == (
        "  b-tool:\n"
        "    command: b\n"
    )
    assert calls == [
        {
            "value": {"b-tool": {"command": "b"}},
            "sort_keys": False,
            "default_flow_style": False,
        }
    ]


def test_project_mcp_file_io_uses_explicit_text_encoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import project_mcp

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_file = project_dir / ".mcp.json"
    _write_project_mcp(project_file, {"covered-tool": {"command": "covered-tool"}})
    claude_config = tmp_path / "claude.json"
    claude_config.write_text(
        json.dumps(
            {
                "projects": {
                    str(project_dir): {
                        "mcpServers": {"covered-tool": {"command": "covered-tool"}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    real_read_text = Path.read_text
    real_write_text = Path.write_text
    checked_reads = {config_path, project_file, claude_config}
    read_calls: list[Path] = []
    write_calls: list[Path] = []

    def checked_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self in checked_reads:
            assert kwargs.get("encoding") == project_mcp.TEXT_ENCODING
            read_calls.append(self)
        return real_read_text(self, *args, **kwargs)

    def checked_write_text(self: Path, data: str, *args: object, **kwargs: object) -> int:
        backup_root = tmp_path / "backups"
        if self in checked_reads or self.parent == backup_root:
            assert kwargs.get("encoding") == project_mcp.TEXT_ENCODING
            write_calls.append(self)
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", checked_read_text)
    monkeypatch.setattr(Path, "write_text", checked_write_text)

    loaded_project = project_mcp._load_mcp_file(project_file)
    loaded_claude = project_mcp._load_claude_project_entries(claude_config, [project_dir])
    project_mcp._append_missing_upstreams(
        config_path,
        {"local-tool": {"command": "local-tool", "profiles": ["codex"]}},
    )
    backup_path = project_mcp._backup_file(project_file, tmp_path / "backups")
    project_mcp._write_empty_mcp_servers(loaded_project)
    project_mcp._write_empty_mcp_servers(loaded_claude[0])

    assert loaded_project.data == {
        "mcpServers": {"covered-tool": {"command": "covered-tool"}}
    }
    assert loaded_claude[0].data["projects"][str(project_dir)]["mcpServers"] == {
        "covered-tool": {"command": "covered-tool"}
    }
    assert backup_path in write_calls
    for path in [config_path, project_file, claude_config]:
        assert path in read_calls
        assert path in write_calls


def test_project_mcp_append_rollback_uses_explicit_text_encoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import project_mcp

    config_path = tmp_path / "broker.yaml"
    _write_broker_config(config_path)
    original = config_path.read_text(encoding="utf-8")
    real_write_text = Path.write_text
    write_calls: list[Path] = []

    def checked_write_text(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if self == config_path:
            assert kwargs.get("encoding") == project_mcp.TEXT_ENCODING
            write_calls.append(self)
        return real_write_text(self, data, *args, **kwargs)

    def reject_updated_config(path: Path) -> object:
        assert path == config_path
        raise ValueError("invalid rendered config")

    monkeypatch.setattr(Path, "write_text", checked_write_text)
    monkeypatch.setattr(project_mcp.BrokerConfig, "from_file", reject_updated_config)

    with pytest.raises(ValueError, match="invalid rendered config"):
        project_mcp._append_missing_upstreams(
            config_path,
            {"bad-tool": {"command": "bad-tool", "profiles": ["codex"]}},
        )

    assert write_calls == [config_path, config_path]
    assert config_path.read_text(encoding="utf-8") == original


def test_project_mcp_claude_writer_preserves_exact_json_format_contract(tmp_path: Path) -> None:
    from mcp_broker import project_mcp

    project = tmp_path / "project"
    project.mkdir()
    claude_config = tmp_path / "claude.json"
    claude_config.write_text(
        json.dumps(
            {
                "top": True,
                "projects": {
                    str(project): {
                        "z": True,
                        "mcpServers": {"covered-tool": {"command": "covered-tool"}},
                        "a": False,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    project_mcp._write_empty_mcp_servers(
        project_mcp._ProjectMcpFile(
            path=claude_config,
            data={},
            servers={"covered-tool": {"command": "covered-tool"}},
            claude_project_path=str(project),
        )
    )

    expected = {
        "top": True,
        "projects": {
            str(project): {
                "z": True,
                "mcpServers": {},
                "a": False,
            }
        },
    }
    assert claude_config.read_text(encoding="utf-8") == json.dumps(
        expected,
        indent=2,
        sort_keys=True,
    ) + "\n"
