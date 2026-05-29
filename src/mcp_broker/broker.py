"""Broker-owned MCP method behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any, Callable

from mcp_broker.config import BrokerSettings, UpstreamConfig
from mcp_broker.profiles import ToolExposureProfile
from mcp_broker.tool_namespace import ToolNamespaceRouter


ToolCaller = Callable[[str, str, dict[str, Any], int], dict[str, Any]]


class UpstreamCallTimeout(Exception):
    """Raised when an upstream tool call exceeds its configured timeout."""


class UpstreamCallCrashed(Exception):
    """Raised when an upstream process exits during a tool call."""


class UpstreamToolNotFound(Exception):
    """Raised when an upstream reports that a routed tool does not exist."""


class BrokerToolError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        upstream_name: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.upstream_name = upstream_name
        self.tool_name = tool_name


@dataclass(frozen=True)
class BrokerCore:
    settings: BrokerSettings
    upstreams: dict[str, UpstreamConfig]
    profile: ToolExposureProfile | None = None
    call_locks: dict[str, threading.Lock] = field(default_factory=dict, compare=False, repr=False)

    def list_tools(self, upstream_tools: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        router = ToolNamespaceRouter(
            broker=self.settings,
            upstreams=self.upstreams,
            profile=self.profile,
        )
        try:
            return {"tools": router.advertise_all_tools(upstream_tools)}
        except ValueError as exc:
            if self._can_compact_after_budget_error(str(exc)):
                return {"tools": router.compact_broker_tools()}
            raise

    def compact_tools(self) -> dict[str, Any]:
        router = ToolNamespaceRouter(
            broker=self.settings,
            upstreams=self.upstreams,
            profile=self.profile,
        )
        return {"tools": router.compact_broker_tools()}

    def call_tool(
        self,
        advertised_name: str,
        arguments: dict[str, Any],
        caller: ToolCaller,
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise BrokerToolError(
                code="invalid_arguments",
                message="tools/call arguments must be an object",
            )
        upstream, upstream_tool_name = self._resolve_call_route(advertised_name)
        if upstream.serialize_calls:
            with self.call_locks.setdefault(upstream.name, threading.Lock()):
                return self._call_resolved_tool(
                    upstream,
                    upstream_tool_name,
                    arguments,
                    caller,
                )
        return self._call_resolved_tool(
            upstream,
            upstream_tool_name,
            arguments,
            caller,
        )

    def _call_resolved_tool(
        self,
        upstream: UpstreamConfig,
        upstream_tool_name: str,
        arguments: dict[str, Any],
        caller: ToolCaller,
    ) -> dict[str, Any]:
        try:
            response = caller(
                upstream.name,
                upstream_tool_name,
                arguments,
                upstream.call_timeout_for_tool(upstream_tool_name),
            )
        except UpstreamCallTimeout as exc:
            raise BrokerToolError(
                code="upstream_timeout",
                message=f"upstream timed out: {upstream.name}",
                upstream_name=upstream.name,
                tool_name=upstream_tool_name,
            ) from exc
        except UpstreamCallCrashed as exc:
            raise BrokerToolError(
                code="upstream_crashed",
                message=f"upstream crashed: {upstream.name}",
                upstream_name=upstream.name,
                tool_name=upstream_tool_name,
            ) from exc
        except UpstreamToolNotFound as exc:
            raise BrokerToolError(
                code="unknown_upstream_tool",
                message=f"upstream tool not found: {upstream.name}.{upstream_tool_name}",
                upstream_name=upstream.name,
                tool_name=upstream_tool_name,
            ) from exc
        self._validate_tool_response(upstream.name, response)
        return response

    def _can_compact_after_budget_error(self, message: str) -> bool:
        return (
            self.profile is not None
            and self.profile.compact_tools_enabled
            and "exceeds tool budget" in message
        )

    def _resolve_call_route(self, advertised_name: str) -> tuple[UpstreamConfig, str]:
        separator = self.settings.tool_namespace_separator
        if separator not in advertised_name:
            raise BrokerToolError(
                code="invalid_tool_name",
                message=f"missing namespace separator: {advertised_name}",
            )
        prefix, upstream_tool_name = advertised_name.split(separator, 1)
        if not upstream_tool_name:
            raise BrokerToolError(
                code="invalid_tool_name",
                message=f"missing upstream tool name: {advertised_name}",
            )
        for upstream in self.upstreams.values():
            upstream_prefix = upstream.tool_prefix or upstream.name
            if upstream_prefix == prefix:
                return self._allowed_call_route(prefix, upstream), upstream_tool_name
        raise BrokerToolError(
            code="unknown_tool_prefix",
            message=f"unknown tool prefix: {prefix}",
        )

    def _allowed_call_route(self, prefix: str, upstream: UpstreamConfig) -> UpstreamConfig:
        if not upstream.enabled or upstream.mode == "disabled":
            raise BrokerToolError(
                code="disabled_prefix",
                message=f"tool prefix disabled: {prefix}",
                upstream_name=upstream.name,
            )
        if self.profile is not None and self.profile.name not in upstream.profiles:
            raise BrokerToolError(
                code="profile_denied",
                message=f"tool prefix denied for profile {self.profile.name}: {prefix}",
                upstream_name=upstream.name,
            )
        if (
            self.profile is not None
            and upstream.mutating
            and not self.profile.allows_mutating_upstream(upstream.name)
        ):
            raise BrokerToolError(
                code="mutating_not_allowed",
                message=(
                    f"mutating upstream not allowed for profile {self.profile.name}: "
                    f"{upstream.name}"
                ),
                upstream_name=upstream.name,
            )
        return upstream

    @staticmethod
    def _validate_tool_response(upstream_name: str, response: dict[str, Any]) -> None:
        if not isinstance(response, dict) or not isinstance(response.get("content"), list):
            raise BrokerToolError(
                code="invalid_upstream_response",
                message=f"invalid upstream tools/call response from {upstream_name}",
                upstream_name=upstream_name,
            )
