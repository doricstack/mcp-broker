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
    assert result.matched_app_directory_files == (app_directory,)
    assert result.matched_tools_cache_files == (tools_cache,)
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


def test_codex_app_policy_aggregates_changes_across_multiple_cache_files(
    tmp_path: Path,
) -> None:
    from mcp_broker.codex_app_policy import (
        CodexAppConnectorPolicy,
        ConnectorSelector,
        apply_codex_app_policy,
    )

    first_app_directory = tmp_path / "app-directory-1.json"
    second_app_directory = tmp_path / "app-directory-2.json"
    first_tools_cache = tmp_path / "tools-cache-1.json"
    second_tools_cache = tmp_path / "tools-cache-2.json"
    for path, payload in [
        (
            first_app_directory,
            {"connectors": [{"id": "connector_search", "name": "Search", "isEnabled": True}]},
        ),
        (
            second_app_directory,
            {"connectors": [{"id": "connector_docs", "name": "Docs", "isEnabled": True}]},
        ),
        (
            first_tools_cache,
            {"tools": [{"connector_id": "connector_search", "connector_name": "Search"}]},
        ),
        (
            second_tools_cache,
            {"tools": [{"connector_id": "connector_docs", "connector_name": "Docs"}]},
        ),
    ]:
        path.write_text(json.dumps(payload), encoding="utf-8")

    result = apply_codex_app_policy(
        CodexAppConnectorPolicy(
            enabled=True,
            app_directory_globs=(str(tmp_path / "app-directory-*.json"),),
            tools_cache_globs=(str(tmp_path / "tools-cache-*.json"),),
            disable_connectors=(
                ConnectorSelector(id="connector_search"),
                ConnectorSelector(id="connector_docs"),
            ),
        ),
        backup_dir=tmp_path / "backups",
        backup_label="policy-test",
        dry_run=True,
    )

    assert result.disabled_connectors == 2
    assert result.removed_tools == 2
    assert result.changed_files == (
        first_app_directory,
        second_app_directory,
        first_tools_cache,
        second_tools_cache,
    )


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


def test_codex_app_policy_does_not_count_already_disabled_connectors() -> None:
    from mcp_broker.codex_app_policy import ConnectorSelector, _disable_connectors

    payload = {
        "connectors": [
            {"id": "connector_search", "name": "Search", "isEnabled": False},
        ]
    }

    assert _disable_connectors(payload, (ConnectorSelector(id="connector_search"),)) == (False, 0)
    assert payload["connectors"][0]["isEnabled"] is False


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

    with pytest.raises(ValueError) as exc_info:
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
    assert expected_error in str(exc_info.value)
    assert not str(exc_info.value).startswith("XX")


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

    with pytest.raises(ValueError) as exc_info:
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
    assert str(exc_info.value) == expected_error


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


def test_codex_app_policy_matches_connector_values_by_id_or_name() -> None:
    from mcp_broker.codex_app_policy import ConnectorSelector, _matches_values

    selectors = (
        ConnectorSelector(id="connector_docs", reason="covered by broker"),
        ConnectorSelector(name="Calendar", reason="covered by broker"),
    )

    assert _matches_values("connector_docs", "Docs", selectors) is True
    assert _matches_values("connector_other", "Calendar", selectors) is True
    assert _matches_values("connector_other", "Other", selectors) is False
    assert _matches_values(None, None, selectors) is False


def test_codex_app_policy_matches_tools_by_top_level_and_meta_values() -> None:
    from mcp_broker.codex_app_policy import ConnectorSelector, _matches_tool

    assert _matches_tool(
        {
            "connector_id": "connector_docs",
            "tool": {"_meta": {"connector_id": "connector_other"}},
        },
        (ConnectorSelector(id="connector_docs"),),
    )
    assert _matches_tool(
        {"tool": {"_meta": {"connector_id": "connector_calendar"}}},
        (ConnectorSelector(id="connector_calendar"),),
    )
    assert _matches_tool(
        {
            "connector_name": "Docs",
            "tool": {"_meta": {"connector_name": "Other"}},
        },
        (ConnectorSelector(name="Docs"),),
    )
    assert _matches_tool(
        {"tool": {"_meta": {"connector_name": "Calendar"}}},
        (ConnectorSelector(name="Calendar"),),
    )
    assert not _matches_tool(
        {
            "connector_id": "connector_docs",
            "connector_name": "Docs",
            "tool": {"_meta": {"connector_id": "connector_calendar"}},
        },
        (ConnectorSelector(id="connector_calendar", name="Calendar"),),
    )
    assert not _matches_tool({"tool": {}}, (ConnectorSelector(id="connector_docs"),))
    assert not _matches_tool(
        {"tool": {"_meta": "bad"}},
        (ConnectorSelector(id="connector_docs", name="Docs"),),
    )


def test_codex_app_policy_backup_creates_nested_backup_directory(tmp_path: Path) -> None:
    from mcp_broker.codex_app_policy import _backup

    source = tmp_path / "cache.json"
    source.write_text("{}", encoding="utf-8")

    backup = _backup(source, backup_dir=tmp_path / "nested" / "backups", backup_label="label")

    assert backup == tmp_path / "nested" / "backups" / "label.cache.json"
    assert backup.read_text(encoding="utf-8") == "{}"


def test_codex_app_policy_writes_stable_json_bytes(tmp_path: Path) -> None:
    from mcp_broker.codex_app_policy import _write_json

    path = tmp_path / "cache.json"

    _write_json(path, {"z": 1, "a": {"b": 2}})

    assert path.read_bytes() == b'{\n  "a": {\n    "b": 2\n  },\n  "z": 1\n}\n'


def test_codex_app_policy_string_or_none_rejects_empty_and_non_string_values() -> None:
    from mcp_broker.codex_app_policy import _string_or_none

    assert _string_or_none("connector_docs") == "connector_docs"
    assert _string_or_none("") is None
    assert _string_or_none(42) is None
