"""Client-render configuration parsing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_broker.codex_app_policy import CodexAppConnectorPolicy, ConnectorSelector


CLIENT_KEYS = frozenset(
    {
        "format",
        "config_path",
        "entry_name",
        "command",
        "args",
        "backup_paths",
        "codex_apps_policy",
        "mcp_allowed_servers",
    }
)
CODEX_APPS_POLICY_KEYS = frozenset(
    {
        "enabled",
        "app_directory_globs",
        "tools_cache_globs",
        "disable_connectors",
    }
)
CONNECTOR_SELECTOR_KEYS = frozenset({"id", "name", "reason"})
SUPPORTED_CLIENT_FORMATS = frozenset({"codex-toml", "claude-json", "mcp-settings-json"})


@dataclass(frozen=True)
class ClientRenderConfig:
    name: str
    format: str
    config_path: Path
    entry_name: str = "mcp-broker"
    command: str = "mcp-broker-client"
    args: tuple[str, ...] = ()
    backup_paths: tuple[Path, ...] = ()
    mcp_allowed_servers: tuple[str, ...] = ()
    codex_apps_policy: CodexAppConnectorPolicy | None = None

    @classmethod
    def from_mapping(
        cls,
        name: str,
        data: dict[str, Any],
        *,
        runtime: object,
        parse_path: Callable[[str, Any], Path],
        expand_config_text: Callable[[str | Path, object], str],
        validate_keys: Callable[[str, dict[str, Any], frozenset[str]], None],
    ) -> "ClientRenderConfig":
        validate_keys(f"clients.{name}", data, CLIENT_KEYS)
        _require_client_keys(name, data)
        config_format = _parse_client_format(name, data["format"])
        args = _parse_list(f"clients.{name}.args", data.get("args", []))
        backup_paths = _parse_list(f"clients.{name}.backup_paths", data.get("backup_paths", []))
        return cls(
            name=name,
            format=config_format,
            config_path=parse_path(f"clients.{name}.config_path", data["config_path"]),
            entry_name=str(data.get("entry_name", "mcp-broker")),
            command=expand_config_text(str(data.get("command", "mcp-broker-client")), runtime),
            args=tuple(expand_config_text(str(arg), runtime) for arg in args),
            backup_paths=tuple(parse_path(f"clients.{name}.backup_paths", path) for path in backup_paths),
            mcp_allowed_servers=_parse_config_strings(
                f"clients.{name}.mcp_allowed_servers",
                data.get("mcp_allowed_servers", []),
                runtime=runtime,
                expand_config_text=expand_config_text,
            ),
            codex_apps_policy=_parse_codex_apps_policy(
                f"clients.{name}.codex_apps_policy",
                data.get("codex_apps_policy"),
                runtime=runtime,
                expand_config_text=expand_config_text,
                validate_keys=validate_keys,
            ),
        )


def _require_client_keys(name: str, data: dict[str, Any]) -> None:
    if "format" not in data:
        raise ValueError(f"missing required config key: clients.{name}.format")
    if "config_path" not in data:
        raise ValueError(f"missing required config key: clients.{name}.config_path")


def _parse_client_format(name: str, value: Any) -> str:
    config_format = str(value)
    if config_format not in SUPPORTED_CLIENT_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_CLIENT_FORMATS))
        raise ValueError(f"clients.{name}.format must be one of: {supported}")
    return config_format


def _parse_list(path: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _parse_codex_apps_policy(
    path: str,
    value: Any,
    *,
    runtime: object,
    expand_config_text: Callable[[str | Path, object], str],
    validate_keys: Callable[[str, dict[str, Any], frozenset[str]], None],
) -> CodexAppConnectorPolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a mapping")
    validate_keys(path, value, CODEX_APPS_POLICY_KEYS)
    disable_connectors = _parse_list(f"{path}.disable_connectors", value.get("disable_connectors", []))
    selectors = tuple(
        _parse_connector_selector(f"{path}.disable_connectors[{index}]", selector, validate_keys)
        for index, selector in enumerate(disable_connectors)
    )
    enabled = _parse_bool(f"{path}.enabled", value.get("enabled", False))
    if enabled and not selectors:
        raise ValueError(f"{path}.disable_connectors must contain at least one connector")
    return CodexAppConnectorPolicy(
        enabled=enabled,
        app_directory_globs=_parse_config_strings(
            f"{path}.app_directory_globs",
            value.get("app_directory_globs", []),
            runtime=runtime,
            expand_config_text=expand_config_text,
        ),
        tools_cache_globs=_parse_config_strings(
            f"{path}.tools_cache_globs",
            value.get("tools_cache_globs", []),
            runtime=runtime,
            expand_config_text=expand_config_text,
        ),
        disable_connectors=selectors,
    )


def _parse_connector_selector(
    path: str,
    value: Any,
    validate_keys: Callable[[str, dict[str, Any], frozenset[str]], None],
) -> ConnectorSelector:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a mapping")
    validate_keys(path, value, CONNECTOR_SELECTOR_KEYS)
    connector_id = _optional_string(f"{path}.id", value.get("id"))
    connector_name = _optional_string(f"{path}.name", value.get("name"))
    if not connector_id and not connector_name:
        raise ValueError(f"{path} must define id or name")
    reason = value.get("reason", "")
    if not isinstance(reason, str):
        raise ValueError(f"{path}.reason must be a string")
    return ConnectorSelector(id=connector_id, name=connector_name, reason=reason)


def _parse_config_strings(
    path: str,
    value: Any,
    *,
    runtime: object,
    expand_config_text: Callable[[str | Path, object], str],
) -> tuple[str, ...]:
    return tuple(expand_config_text(str(item), runtime) for item in _parse_list(path, value))


def _optional_string(path: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _parse_bool(path: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    return value
