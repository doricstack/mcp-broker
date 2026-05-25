"""Client profile definitions for broker tool exposure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolExposureProfile:
    name: str
    max_tools: int
    compact_tools_enabled: bool = False
    allow_mutating_upstreams: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("profile name cannot be empty")
        if self.max_tools <= 0:
            raise ValueError("profile max_tools must be greater than 0")
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
            allow_mutating_upstreams=allow_mutating_upstreams,
        )

    def allows_mutating_upstream(self, upstream_name: str) -> bool:
        return upstream_name in self.allow_mutating_upstreams


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
