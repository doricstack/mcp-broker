"""Broker facade catalog behavior."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from mcp_broker.broker import BrokerCore, BrokerToolError
from mcp_broker.config import BrokerConfig, UpstreamConfig
from mcp_broker.profiles import ToolExposureProfile


ToolLister = Callable[[str, int], list[dict[str, object]]]
ToolCaller = Callable[[str, str, dict[str, Any], int], dict[str, Any]]
StatusProvider = Callable[[set[str] | None], dict[str, dict[str, object]]]
_CLIENT_CONTROL_ARGUMENTS = frozenset({"wait_for_previous"})


class BrokerCatalogFacade:
    def __init__(
        self,
        *,
        broker_config: BrokerConfig,
        profile: ToolExposureProfile | None,
        list_upstream: ToolLister,
        call_upstream: ToolCaller,
        call_locks: dict[str, threading.Lock],
        status_provider: StatusProvider | None = None,
    ) -> None:
        self._broker_config = broker_config
        self._profile = profile
        self._list_upstream = list_upstream
        self._call_upstream = call_upstream
        self._call_locks = call_locks
        self._status_provider = status_provider or (lambda _visible_upstreams: {})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        canonical_name = self._canonical_broker_tool_name(name)
        if canonical_name == "broker.search_tools":
            return self._search_tools(arguments)
        if canonical_name == "broker.describe_tool":
            return self._describe_tool(arguments)
        if canonical_name == "broker.call_tool":
            return self._call_managed_tool(arguments)
        if canonical_name == "broker.status":
            return self._status(arguments)
        raise BrokerToolError(code="unknown_broker_tool", message=f"unknown broker tool: {name}")

    def _canonical_broker_tool_name(self, name: str) -> str:
        if self._profile is None:
            return name
        return self._profile.canonical_broker_tool_name(name)

    def _search_tools(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        limit = int(arguments.get("limit", 20))
        entries, skipped_upstreams = self._catalog_entries(query=query, tool_name="")
        matches = [
            entry
            for entry in entries
            if catalog_entry_matches(entry, query)
        ][:limit]
        result: dict[str, Any] = {"matches": matches}
        if skipped_upstreams:
            result["skipped_upstreams"] = skipped_upstreams
        return structured_tool_result(result)

    def _describe_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_name = arguments.get("name")
        if not isinstance(tool_name, str):
            raise ValueError("broker.describe_tool requires string name")
        entries, _skipped_upstreams = self._catalog_entries(query="", tool_name=tool_name)
        for entry in entries:
            if entry["name"] == tool_name:
                return structured_tool_result({"tool": entry})
        raise ValueError(f"broker tool not found: {tool_name}")

    def _call_managed_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_name = arguments.get("name")
        tool_arguments = arguments.get("arguments", {})
        if not isinstance(tool_name, str) or not isinstance(tool_arguments, dict):
            raise ValueError("broker.call_tool requires name and object arguments")
        core = BrokerCore(
            settings=self._broker_config.broker,
            upstreams=self._broker_config.upstreams,
            profile=self._profile,
            call_locks=self._call_locks,
        )
        return core.call_tool(tool_name, tool_arguments, self._call_upstream)

    def _status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        status_arguments = {
            name: value
            for name, value in arguments.items()
            if name not in _CLIENT_CONTROL_ARGUMENTS
        }
        if status_arguments:
            raise ValueError("broker.status does not accept arguments")
        exposed_upstreams = {
            upstream_name
            for upstream_name, upstream in self._broker_config.upstreams.items()
            if self._status_exposes_upstream(upstream_name, upstream)
        }
        health = self._status_provider(exposed_upstreams)
        upstreams = {}
        for upstream_name, upstream in self._broker_config.upstreams.items():
            exposed = self._status_exposes_upstream(upstream_name, upstream)
            if not exposed and upstream.enabled and upstream.mode != "disabled":
                continue
            snapshot = health.get(upstream_name, {})
            upstreams[upstream_name] = {
                "enabled": upstream.enabled,
                "auth_repair_attempts": _snapshot_int(snapshot, "auth_repair_attempts"),
                "auth_repair_failures": _snapshot_int(snapshot, "auth_repair_failures"),
                "auth_repair_successes": _snapshot_int(snapshot, "auth_repair_successes"),
                "auth_probe": str(snapshot.get("auth_probe", "none")),
                "auth_state": _auth_state(snapshot),
                "exposed": exposed,
                "last_error": snapshot.get("last_error"),
                "mode": upstream.mode,
                "mutating": upstream.mutating,
                "pid": snapshot.get("pid"),
                "restarts": snapshot.get("restarts"),
                "session_count": _snapshot_int(snapshot, "session_count", "sessions"),
                "state": snapshot.get(
                    "state",
                    "configured" if upstream.enabled and upstream.mode != "disabled" else "disabled",
                ),
                "transport": upstream.transport,
            }
        return structured_tool_result(
            {
                "profile": self._profile.name if self._profile is not None else None,
                "socket_path": str(self._broker_config.runtime.socket_path),
                "status": _broker_status(upstreams),
                "upstreams": upstreams,
            }
        )

    def _status_exposes_upstream(self, upstream_name: str, upstream: UpstreamConfig) -> bool:
        if not upstream.enabled or upstream.mode == "disabled":
            return False
        if not profile_allows_upstream(self._profile, upstream):
            return False
        return not (
            upstream.mutating
            and self._profile is not None
            and not self._profile.allows_mutating_upstream(upstream_name)
        )

    def _catalog_entries(
        self,
        query: str,
        tool_name: str,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        if not isinstance(query, str) or not isinstance(tool_name, str):
            raise TypeError("query and tool_name must be strings")
        if query and tool_name:
            raise ValueError("use query or tool_name, not both")
        entries = []
        skipped_upstreams = {}
        for upstream_name, upstream in self._catalog_upstreams(
            query=query,
            tool_name=tool_name,
        ).items():
            try:
                tools = self._list_upstream(upstream_name, upstream.health.call_timeout_seconds)
            except Exception as exc:
                error = str(exc)
                skipped_upstreams[upstream_name] = error
                entries.append(catalog_unavailable_entry_for_upstream(upstream, error))
                continue
            entries.extend(
                catalog_entries_for_upstream(
                    upstream,
                    tools,
                    self._broker_config.broker.tool_namespace_separator,
                )
            )
        return entries, skipped_upstreams

    def _catalog_upstreams(
        self,
        query: str,
        tool_name: str,
    ) -> dict[str, UpstreamConfig]:
        upstreams = {}
        for upstream_name, upstream in self._broker_config.upstreams.items():
            if not upstream.enabled or upstream.mode == "disabled":
                continue
            if not profile_allows_upstream(self._profile, upstream):
                continue
            if (
                upstream.mutating
                and self._profile is not None
                and not self._profile.allows_mutating_upstream(upstream_name)
            ):
                continue
            upstreams[upstream_name] = upstream
        if tool_name:
            matched_by_tool_name = {
                name: upstream
                for name, upstream in upstreams.items()
                if upstream_owns_tool_name(
                    upstream,
                    tool_name,
                    self._broker_config.broker.tool_namespace_separator,
                )
            }
            if matched_by_tool_name:
                return matched_by_tool_name
        if not _specific_query_can_select_upstream(query):
            return upstreams
        matched = {
            name: upstream
            for name, upstream in upstreams.items()
            if upstream_metadata_matches(upstream, query)
        }
        return matched or upstreams


def _snapshot_int(snapshot: dict[str, object], *keys: str) -> int:
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, int):
            return value
    return 0


def _auth_state(snapshot: dict[str, object]) -> str:
    value = snapshot.get("auth_state")
    if value in {"authenticated", "unauthenticated", "unknown"}:
        return str(value)
    last_error = snapshot.get("last_error")
    if isinstance(last_error, str) and _looks_like_auth_error(last_error):
        return "unauthenticated"
    return "unknown"


def _looks_like_auth_error(message: str) -> bool:
    normalized = message.lower()
    return any(
        marker in normalized
        for marker in (
            "auth",
            "credential",
            "forbidden",
            "token",
            "unauthorized",
            "401",
            "403",
        )
    )


def _broker_status(upstreams: dict[str, dict[str, Any]]) -> str:
    for upstream in upstreams.values():
        if upstream.get("last_error"):
            return "degraded"
        if upstream.get("state") in {"exited", "failed", "backoff"}:
            return "degraded"
    return "ok"


def profile_allows_upstream(
    profile: ToolExposureProfile | None,
    upstream: UpstreamConfig,
) -> bool:
    if profile is None:
        return True
    return profile.name in upstream.profiles


def catalog_entries_for_upstream(
    upstream: UpstreamConfig,
    tools: list[dict[str, object]],
    separator: str,
) -> list[dict[str, Any]]:
    prefix = upstream.tool_prefix or upstream.name
    entries = []
    for tool in tools:
        tool_name = str(tool.get("name", ""))
        if not tool_name:
            continue
        entries.append(
            {
                "name": f"{prefix}{separator}{tool_name}",
                "upstream": upstream.name,
                "description": str(tool.get("description", "")),
                "inputSchema": tool.get("inputSchema", {"type": "object"}),
                "purpose": upstream.purpose,
                "tags": list(upstream.tags),
                "mutating": upstream.mutating,
            }
        )
    return entries


def catalog_unavailable_entry_for_upstream(
    upstream: UpstreamConfig,
    error: str,
) -> dict[str, Any]:
    return {
        "name": upstream.name,
        "upstream": upstream.name,
        "description": f"upstream unavailable: {error}",
        "purpose": upstream.purpose,
        "tags": list(upstream.tags),
        "mutating": upstream.mutating,
        "available": False,
    }


def catalog_entry_matches(entry: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            str(entry.get("name", "")),
            str(entry.get("upstream", "")),
            str(entry.get("description", "")),
            str(entry.get("purpose", "")),
            " ".join(str(tag) for tag in entry.get("tags", [])),
        ]
    ).lower()
    return all(token in haystack for token in query.lower().split())


def upstream_metadata_matches(upstream: UpstreamConfig, query: str) -> bool:
    smoke_query = upstream.smoke.query if upstream.smoke is not None else ""
    smoke_tool = upstream.smoke.tool if upstream.smoke is not None else ""
    prefix = upstream.tool_prefix or upstream.name
    return catalog_entry_matches(
        {
            "name": f"{upstream.name} {prefix} {smoke_tool}",
            "description": smoke_query,
            "purpose": upstream.purpose,
            "tags": list(upstream.tags),
        },
        query,
    )


def upstream_owns_tool_name(upstream: UpstreamConfig, tool_name: str, separator: str) -> bool:
    prefix = upstream.tool_prefix or upstream.name
    return tool_name.startswith(f"{prefix}{separator}")


def _specific_query_can_select_upstream(query: str) -> bool:
    return len(query.split()) >= 2


def structured_tool_result(structured_content: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured_content, sort_keys=True),
            }
        ],
        "structuredContent": structured_content,
    }
