from pathlib import Path
from typing import Any

import pytest


pytestmark = pytest.mark.unit


class _Runtime:
    root = Path("/runtime")


def _expand_text(value: str | Path, runtime: object) -> str:
    return str(value).replace("{root}", str(getattr(runtime, "root")))


def _validate_keys(
    calls: list[tuple[str, dict[str, Any], frozenset[str]]],
):
    def validate(path: str, value: dict[str, Any], allowed: frozenset[str]) -> None:
        calls.append((path, value, allowed))
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown config key: {path}.{unknown[0]}")

    return validate


def test_client_render_config_codex_policy_defaults_disabled_with_empty_lists() -> None:
    from mcp_broker.client_config import _parse_codex_apps_policy

    calls: list[tuple[str, dict[str, Any], frozenset[str]]] = []

    policy = _parse_codex_apps_policy(
        "clients.codex.codex_apps_policy",
        {},
        runtime=_Runtime(),
        expand_config_text=_expand_text,
        validate_keys=_validate_keys(calls),
    )

    assert policy is not None
    assert policy.enabled is False
    assert policy.app_directory_globs == ()
    assert policy.tools_cache_globs == ()
    assert policy.disable_connectors == ()
    assert [call[0] for call in calls] == ["clients.codex.codex_apps_policy"]


@pytest.mark.parametrize(
    ("field", "expected_path"),
    [
        ("app_directory_globs", "clients.codex.codex_apps_policy.app_directory_globs"),
        ("tools_cache_globs", "clients.codex.codex_apps_policy.tools_cache_globs"),
    ],
)
def test_client_render_config_codex_policy_reports_glob_list_paths(
    field: str,
    expected_path: str,
) -> None:
    from mcp_broker.client_config import _parse_codex_apps_policy

    with pytest.raises(ValueError, match=f"{expected_path} must be a list"):
        _parse_codex_apps_policy(
            "clients.codex.codex_apps_policy",
            {field: "not-a-list"},
            runtime=_Runtime(),
            expand_config_text=_expand_text,
            validate_keys=_validate_keys([]),
        )


def test_client_render_config_codex_policy_expands_globs_and_selectors() -> None:
    from mcp_broker.client_config import _parse_codex_apps_policy

    calls: list[tuple[str, dict[str, Any], frozenset[str]]] = []

    policy = _parse_codex_apps_policy(
        "clients.codex.codex_apps_policy",
        {
            "enabled": True,
            "app_directory_globs": ["{root}/apps/*.json"],
            "tools_cache_globs": ["{root}/tools/*.json"],
            "disable_connectors": [
                {"id": "connector_docs", "name": "Docs", "reason": "broker owns Docs"}
            ],
        },
        runtime=_Runtime(),
        expand_config_text=_expand_text,
        validate_keys=_validate_keys(calls),
    )

    assert policy is not None
    assert policy.enabled is True
    assert policy.app_directory_globs == ("/runtime/apps/*.json",)
    assert policy.tools_cache_globs == ("/runtime/tools/*.json",)
    assert [(selector.id, selector.name, selector.reason) for selector in policy.disable_connectors] == [
        ("connector_docs", "Docs", "broker owns Docs")
    ]
    assert [call[0] for call in calls] == [
        "clients.codex.codex_apps_policy",
        "clients.codex.codex_apps_policy.disable_connectors[0]",
    ]


def test_client_render_config_connector_selector_defaults_reason_only() -> None:
    from mcp_broker.client_config import _parse_connector_selector

    calls: list[tuple[str, dict[str, Any], frozenset[str]]] = []

    selector = _parse_connector_selector(
        "clients.codex.codex_apps_policy.disable_connectors[0]",
        {"id": "connector_docs", "name": "Docs"},
        _validate_keys(calls),
    )

    assert selector.id == "connector_docs"
    assert selector.name == "Docs"
    assert selector.reason == ""
    assert [call[0] for call in calls] == [
        "clients.codex.codex_apps_policy.disable_connectors[0]"
    ]


def test_client_render_config_connector_selector_preserves_explicit_reason() -> None:
    from mcp_broker.client_config import _parse_connector_selector

    selector = _parse_connector_selector(
        "clients.codex.codex_apps_policy.disable_connectors[0]",
        {"id": "connector_docs", "name": "Docs", "reason": "broker owns Docs"},
        _validate_keys([]),
    )

    assert selector.id == "connector_docs"
    assert selector.name == "Docs"
    assert selector.reason == "broker owns Docs"


def test_client_render_config_optional_string_accepts_none_and_non_empty_values() -> None:
    from mcp_broker.client_config import _optional_string

    assert _optional_string("clients.generic.entry_name", None) is None
    assert _optional_string("clients.generic.entry_name", "mcp-broker") == "mcp-broker"


@pytest.mark.parametrize("value", ["", 123, Path("mcp-broker")])
def test_client_render_config_optional_string_rejects_invalid_values(value: object) -> None:
    from mcp_broker.client_config import _optional_string

    with pytest.raises(
        ValueError,
        match="clients.generic.entry_name must be a non-empty string",
    ):
        _optional_string("clients.generic.entry_name", value)
