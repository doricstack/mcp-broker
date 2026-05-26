"""Client profile definitions for broker tool exposure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


BROKER_TOOL_NAME_STYLES = frozenset({"dotted", "snake"})
_BROKER_TOOL_NAMES = {
    "broker.search_tools",
    "broker.describe_tool",
    "broker.call_tool",
    "broker.status",
}
_BROKER_TOOL_SNAKE_ALIASES = {
    name.replace(".", "_"): name
    for name in _BROKER_TOOL_NAMES
}


@dataclass(frozen=True)
class ToolExposureProfile:
    name: str
    max_tools: int
    compact_tools_enabled: bool = False
    broker_tool_name_style: str = "dotted"
    allow_mutating_upstreams: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("profile name cannot be empty")
        if self.max_tools <= 0:
            raise ValueError("profile max_tools must be greater than 0")
        if not isinstance(self.broker_tool_name_style, str):
            raise ValueError("profile broker_tool_name_style must be a string")
        if self.broker_tool_name_style not in BROKER_TOOL_NAME_STYLES:
            allowed = ", ".join(sorted(BROKER_TOOL_NAME_STYLES))
            raise ValueError(f"profile broker_tool_name_style must be one of: {allowed}")
        for upstream_name in self.allow_mutating_upstreams:
            if not upstream_name:
                raise ValueError("profile allow_mutating_upstreams cannot include empty values")

    @classmethod
    def from_mapping(cls, name: str, data: dict[str, Any]) -> "ToolExposureProfile":
        if "max_tools" not in data:
            raise ValueError(f"profiles.{name}.max_tools is required")
        allow_mutating_upstreams = _parse_allow_mutating_upstreams(name, data)
        return cls(
            name=name,
            max_tools=int(data["max_tools"]),
            compact_tools_enabled=bool(data.get("compact_tools_enabled", False)),
            broker_tool_name_style=data.get("broker_tool_name_style", "dotted"),
            allow_mutating_upstreams=allow_mutating_upstreams,
        )

    def allows_mutating_upstream(self, upstream_name: str) -> bool:
        return upstream_name in self.allow_mutating_upstreams

    def exposed_broker_tool_name(self, canonical_name: str) -> str:
        if self.broker_tool_name_style == "snake":
            return canonical_name.replace(".", "_")
        return canonical_name

    def canonical_broker_tool_name(self, name: str) -> str:
        if name in _BROKER_TOOL_NAMES:
            return name
        if self.broker_tool_name_style == "snake":
            return _BROKER_TOOL_SNAKE_ALIASES.get(name, name)
        return name


def _parse_allow_mutating_upstreams(name: str, data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("allow_mutating_upstreams", [])
    if not isinstance(raw, list):
        raise ValueError(f"profiles.{name}.allow_mutating_upstreams must be a list")
    parsed: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value:
            raise ValueError(f"profiles.{name}.allow_mutating_upstreams must contain upstream names")
        parsed.append(value)
    return tuple(parsed)
