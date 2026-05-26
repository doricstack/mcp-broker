"""Tool namespace mapping for configured upstream MCP servers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from mcp_broker.config import BrokerSettings, UpstreamConfig
from mcp_broker.profiles import ToolExposureProfile


@dataclass(frozen=True)
class ToolRoute:
    upstream_name: str
    upstream_tool_name: str


class ToolNamespaceRouter:
    def __init__(
        self,
        *,
        broker: BrokerSettings,
        upstreams: dict[str, UpstreamConfig],
        profile: ToolExposureProfile | None = None,
    ) -> None:
        if not broker.tool_namespace_separator:
            raise ValueError("broker.tool_namespace_separator cannot be empty")
        self._separator = broker.tool_namespace_separator
        self._profile = profile
        self._upstreams = dict(upstreams)
        self._prefix_to_upstream = self._build_prefix_index(upstreams, profile)

    @staticmethod
    def _build_prefix_index(
        upstreams: dict[str, UpstreamConfig],
        profile: ToolExposureProfile | None,
    ) -> dict[str, str]:
        index: dict[str, str] = {}
        for upstream_name, upstream in upstreams.items():
            if not upstream.enabled or upstream.mode == "disabled":
                continue
            if profile is not None and profile.name not in upstream.profiles:
                continue
            prefix = upstream.tool_prefix or upstream.name
            if prefix in index:
                raise ValueError(f"duplicate tool prefix: {prefix}")
            index[prefix] = upstream_name
        return index

    def advertise_tools(
        self,
        upstream_name: str,
        upstream_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        upstream = self._enabled_upstream(upstream_name)
        self._enforce_mutating_allowlist(upstream)
        prefix = upstream.tool_prefix or upstream.name
        advertised = []
        for tool in upstream_tools:
            tool_name = str(tool.get("name", ""))
            if not tool_name:
                raise ValueError(f"upstream tool missing name: {upstream_name}")
            namespaced = deepcopy(tool)
            namespaced["name"] = f"{prefix}{self._separator}{tool_name}"
            advertised.append(namespaced)
        return advertised

    def advertise_all_tools(
        self,
        upstream_tools: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        advertised = []
        names = set()
        for upstream_name, tools in upstream_tools.items():
            if self._upstream_allowed(upstream_name):
                for tool in self.advertise_tools(upstream_name, tools):
                    tool_name = str(tool["name"])
                    if tool_name in names:
                        raise ValueError(f"duplicate advertised tool: {tool_name}")
                    names.add(tool_name)
                    advertised.append(tool)
        self._enforce_profile_budget(len(advertised))
        return advertised

    def compact_broker_tools(self) -> list[dict[str, Any]]:
        profile = self._profile
        if profile is None or not profile.compact_tools_enabled:
            return []
        return [
            _broker_tool(
                self._compact_broker_tool_name(profile, "broker.search_tools"),
                "Search broker-managed upstream tools",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "required": ["query"],
                },
            ),
            _broker_tool(
                self._compact_broker_tool_name(profile, "broker.describe_tool"),
                "Describe one broker-managed upstream tool",
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            _broker_tool(
                self._compact_broker_tool_name(profile, "broker.call_tool"),
                "Call one broker-managed upstream tool",
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["name", "arguments"],
                },
            ),
            _broker_tool(
                self._compact_broker_tool_name(profile, "broker.status"),
                "Report broker-managed upstream status for this profile",
                {
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    def _compact_broker_tool_name(self, profile: ToolExposureProfile, canonical_name: str) -> str:
        return profile.exposed_broker_tool_name(canonical_name)

    def resolve_tool_name(self, advertised_name: str) -> ToolRoute:
        if self._separator not in advertised_name:
            raise ValueError(f"missing namespace separator: {advertised_name}")
        prefix, upstream_tool_name = advertised_name.split(self._separator, 1)
        if not upstream_tool_name:
            raise ValueError(f"missing upstream tool name: {advertised_name}")
        upstream_name = self._prefix_to_upstream.get(prefix)
        if upstream_name is None:
            raise ValueError(f"unknown tool prefix: {prefix}")
        return ToolRoute(
            upstream_name=upstream_name,
            upstream_tool_name=upstream_tool_name,
        )

    def _enabled_upstream(self, upstream_name: str) -> UpstreamConfig:
        upstream = self._upstreams.get(upstream_name)
        if upstream is None:
            raise ValueError(f"unknown upstream: {upstream_name}")
        if not upstream.enabled or upstream.mode == "disabled":
            raise ValueError(f"upstream disabled: {upstream_name}")
        if not self._upstream_allowed(upstream_name):
            raise ValueError(f"upstream not exposed to profile: {upstream_name}")
        return upstream

    def _upstream_allowed(self, upstream_name: str) -> bool:
        upstream = self._upstreams.get(upstream_name)
        if upstream is None or not upstream.enabled or upstream.mode == "disabled":
            return False
        if self._profile is None:
            return True
        return self._profile.name in upstream.profiles

    def _enforce_profile_budget(self, tool_count: int) -> None:
        if self._profile is None:
            return
        if tool_count > self._profile.max_tools:
            raise ValueError(
                f"profile {self._profile.name} exceeds tool budget: "
                f"{tool_count} > {self._profile.max_tools}"
            )

    def _enforce_mutating_allowlist(self, upstream: UpstreamConfig) -> None:
        if not upstream.mutating or self._profile is None:
            return
        if not self._profile.allows_mutating_upstream(upstream.name):
            raise ValueError(f"mutating upstream not allowed for profile: {upstream.name}")


def _broker_tool(name: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
    }
