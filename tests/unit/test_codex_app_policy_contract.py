import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_codex_app_policy_disables_configured_connectors_and_removes_tools(tmp_path: Path) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        ConnectorSelector,
        apply_codex_app_policy,
    )

    app_directory = tmp_path / "app-directory.json"
    tools_cache = tmp_path / "tools-cache.json"
    app_directory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connectors": [
                    {"id": "connector_github", "name": "GitHub", "isEnabled": True},
                    {"id": "connector_canva", "name": "Canva", "isEnabled": True},
                    {"id": "connector_figma", "name": "Figma", "isEnabled": True},
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
                    {
                        "tool": {
                            "_meta": {
                                "connector_id": "connector_figma",
                                "connector_name": "Figma",
                            }
                        }
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = apply_codex_app_policy(
        CodexAppConnectorPolicy(
            enabled=True,
            app_directory_globs=(str(app_directory),),
            tools_cache_globs=(str(tools_cache),),
            disable_connectors=(
                ConnectorSelector(id="connector_github", name="GitHub", reason="broker owns it"),
                ConnectorSelector(id=None, name="Figma", reason="broker owns it"),
            ),
        ),
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=False,
    )

    directory_after = json.loads(app_directory.read_text(encoding="utf-8"))
    tools_after = json.loads(tools_cache.read_text(encoding="utf-8"))

    assert result.disabled_connectors == 2
    assert result.removed_tools == 2
    assert result.changed_files == (app_directory, tools_cache)
    assert (tmp_path / "backups" / "policy-test.app-directory.json").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "backups" / "policy-test.tools-cache.json").read_text(encoding="utf-8")
    assert [
        (connector["name"], connector["isEnabled"])
        for connector in directory_after["connectors"]
    ] == [
        ("GitHub", False),
        ("Canva", True),
        ("Figma", False),
    ]
    assert [tool.get("connector_name") for tool in tools_after["tools"]] == ["Canva"]


def test_codex_app_policy_dry_run_reports_changes_without_writing(tmp_path: Path) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        ConnectorSelector,
        apply_codex_app_policy,
    )

    app_directory = tmp_path / "app-directory.json"
    before = {
        "schema_version": 1,
        "connectors": [{"id": "connector_github", "name": "GitHub", "isEnabled": True}],
    }
    app_directory.write_text(json.dumps(before), encoding="utf-8")

    result = apply_codex_app_policy(
        CodexAppConnectorPolicy(
            enabled=True,
            app_directory_globs=(str(app_directory),),
            tools_cache_globs=(),
            disable_connectors=(ConnectorSelector(id="connector_github", name=None, reason=""),),
        ),
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=True,
    )

    assert result.disabled_connectors == 1
    assert result.changed_files == (app_directory,)
    assert json.loads(app_directory.read_text(encoding="utf-8")) == before
    assert not (tmp_path / "backups").exists()


def test_codex_app_policy_reports_unchanged_files_and_dry_run_tool_removals(
    tmp_path: Path,
) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        ConnectorSelector,
        apply_codex_app_policy,
    )

    app_directory = tmp_path / "app-directory.json"
    unmatched_tools_cache = tmp_path / "unmatched-tools-cache.json"
    removable_tools_cache = tmp_path / "removable-tools-cache.json"
    app_directory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "connectors": [
                    {"id": "connector_notes", "name": "Notes", "isEnabled": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    unmatched_tools_cache.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tools": [
                    {"connector_id": "connector_notes", "connector_name": "Notes", "tool": {}},
                ],
            }
        ),
        encoding="utf-8",
    )
    removable_before = {
        "schema_version": 1,
        "tools": [
            {"connector_id": "connector_search", "connector_name": "Search", "tool": {}},
            {"connector_id": "connector_notes", "connector_name": "Notes", "tool": {}},
        ],
    }
    removable_tools_cache.write_text(json.dumps(removable_before), encoding="utf-8")

    unchanged = apply_codex_app_policy(
        CodexAppConnectorPolicy(
            enabled=True,
            app_directory_globs=(str(app_directory),),
            tools_cache_globs=(str(unmatched_tools_cache),),
            disable_connectors=(ConnectorSelector(id="connector_search", name="Search"),),
        ),
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=False,
    )
    dry_run = apply_codex_app_policy(
        CodexAppConnectorPolicy(
            enabled=True,
            app_directory_globs=(),
            tools_cache_globs=(str(removable_tools_cache),),
            disable_connectors=(ConnectorSelector(id="connector_search", name="Search"),),
        ),
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=True,
    )

    assert unchanged.changed_files == ()
    assert unchanged.disabled_connectors == 0
    assert unchanged.removed_tools == 0
    assert dry_run.changed_files == (removable_tools_cache,)
    assert dry_run.removed_tools == 1
    assert json.loads(removable_tools_cache.read_text(encoding="utf-8")) == removable_before
    assert not (tmp_path / "backups").exists()


def test_codex_app_policy_disabled_or_missing_policy_is_noop(tmp_path: Path) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        apply_codex_app_policy,
    )

    missing_result = apply_codex_app_policy(
        None,
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=True,
    )
    disabled_result = apply_codex_app_policy(
        CodexAppConnectorPolicy(enabled=False),
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=False,
    )

    assert missing_result.changed_files == ()
    assert missing_result.dry_run is True
    assert disabled_result.changed_files == ()
    assert disabled_result.dry_run is False


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ([], "Codex app cache must be a JSON object"),
        ({"connectors": "bad"}, "Codex app directory cache must contain a connectors list"),
        ({"connectors": ["bad"]}, "Codex app directory connectors must be objects"),
    ],
)
def test_codex_app_policy_rejects_invalid_app_directory_cache(
    tmp_path: Path,
    payload: object,
    expected_error: str,
) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        ConnectorSelector,
        apply_codex_app_policy,
    )

    app_directory = tmp_path / "app-directory.json"
    app_directory.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        apply_codex_app_policy(
            CodexAppConnectorPolicy(
                enabled=True,
                app_directory_globs=(str(app_directory),),
                tools_cache_globs=(),
                disable_connectors=(ConnectorSelector(id="connector_github"),),
            ),
            backup_dir=tmp_path / "backups",
            backup_label="policy-test",
            dry_run=True,
        )


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ({"tools": "bad"}, "Codex app tools cache must contain a tools list"),
        ({"tools": ["bad"]}, "Codex app tool records must be objects"),
    ],
)
def test_codex_app_policy_rejects_invalid_tools_cache(
    tmp_path: Path,
    payload: object,
    expected_error: str,
) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        ConnectorSelector,
        apply_codex_app_policy,
    )

    tools_cache = tmp_path / "tools-cache.json"
    tools_cache.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        apply_codex_app_policy(
            CodexAppConnectorPolicy(
                enabled=True,
                app_directory_globs=(),
                tools_cache_globs=(str(tools_cache),),
                disable_connectors=(ConnectorSelector(id="connector_github"),),
            ),
            backup_dir=tmp_path / "backups",
            backup_label="policy-test",
            dry_run=True,
        )


def test_codex_app_policy_reports_unmatched_globs(tmp_path: Path) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        ConnectorSelector,
        apply_codex_app_policy,
    )

    result = apply_codex_app_policy(
        CodexAppConnectorPolicy(
            enabled=True,
            app_directory_globs=(str(tmp_path / "missing-apps" / "*.json"),),
            tools_cache_globs=(str(tmp_path / "missing-tools" / "*.json"),),
            disable_connectors=(ConnectorSelector(name="GitHub"),),
        ),
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=True,
    )

    assert result.warnings == (
        f"app_directory_globs matched no files: {tmp_path}/missing-apps/*.json",
        f"tools_cache_globs matched no files: {tmp_path}/missing-tools/*.json",
    )
