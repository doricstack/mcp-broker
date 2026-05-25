"""Zero-dependency configuration schema primitives for mcp-broker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_UPSTREAM_MODES = frozenset({"shared", "per_session", "disabled"})
ALLOWED_UPSTREAM_TRANSPORTS = frozenset({"stdio", "http", "sse"})

DEFAULT_STARTUP_TIMEOUT_SECONDS = 60
DEFAULT_RESTART_MAX_ATTEMPTS = 3
DEFAULT_RESTART_BACKOFF_SECONDS = 2
DEFAULT_READY_TIMEOUT_SECONDS = 10
DEFAULT_CALL_TIMEOUT_SECONDS = 60
DEFAULT_HTTP_RETRY_ATTEMPTS = 0
DEFAULT_HTTP_RETRY_BACKOFF_SECONDS = 0
DEFAULT_IDLE_TIMEOUT_SECONDS = 900
DEFAULT_CPU_WATCHDOG_PERCENT = 80
DEFAULT_CPU_WATCHDOG_SECONDS = 10
DEFAULT_AUTH_REPAIR_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class RestartPolicy:
    max_attempts: int = DEFAULT_RESTART_MAX_ATTEMPTS
    backoff_seconds: int = DEFAULT_RESTART_BACKOFF_SECONDS

    @classmethod
    def from_mapping(cls, path: str, data: dict[str, Any] | None) -> "RestartPolicy":
        raw = _mapping_or_empty(path, data)
        _validate_keys(path, raw, {"max_attempts", "backoff_seconds"})
        max_attempts = _non_negative_int(
            f"{path}.max_attempts",
            raw.get("max_attempts", DEFAULT_RESTART_MAX_ATTEMPTS),
        )
        backoff_seconds = _positive_int(
            f"{path}.backoff_seconds",
            raw.get("backoff_seconds", DEFAULT_RESTART_BACKOFF_SECONDS),
        )
        return cls(max_attempts=max_attempts, backoff_seconds=backoff_seconds)


@dataclass(frozen=True)
class HealthPolicy:
    ready_timeout_seconds: int = DEFAULT_READY_TIMEOUT_SECONDS
    call_timeout_seconds: int = DEFAULT_CALL_TIMEOUT_SECONDS
    http_retry_attempts: int = DEFAULT_HTTP_RETRY_ATTEMPTS
    http_retry_backoff_seconds: int = DEFAULT_HTTP_RETRY_BACKOFF_SECONDS

    @classmethod
    def from_mapping(cls, path: str, data: dict[str, Any] | None) -> "HealthPolicy":
        raw = _mapping_or_empty(path, data)
        _validate_keys(
            path,
            raw,
            {
                "ready_timeout_seconds",
                "call_timeout_seconds",
                "http_retry_attempts",
                "http_retry_backoff_seconds",
            },
        )
        ready_timeout_seconds = _positive_int(
            f"{path}.ready_timeout_seconds",
            raw.get("ready_timeout_seconds", DEFAULT_READY_TIMEOUT_SECONDS),
        )
        call_timeout_seconds = _positive_int(
            f"{path}.call_timeout_seconds",
            raw.get("call_timeout_seconds", DEFAULT_CALL_TIMEOUT_SECONDS),
        )
        return cls(
            ready_timeout_seconds=ready_timeout_seconds,
            call_timeout_seconds=call_timeout_seconds,
            http_retry_attempts=_non_negative_int(
                f"{path}.http_retry_attempts",
                raw.get("http_retry_attempts", DEFAULT_HTTP_RETRY_ATTEMPTS),
            ),
            http_retry_backoff_seconds=_non_negative_int(
                f"{path}.http_retry_backoff_seconds",
                raw.get("http_retry_backoff_seconds", DEFAULT_HTTP_RETRY_BACKOFF_SECONDS),
            ),
        )


@dataclass(frozen=True)
class ResourcePolicy:
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS
    cpu_watchdog_percent: int = DEFAULT_CPU_WATCHDOG_PERCENT
    cpu_watchdog_seconds: int = DEFAULT_CPU_WATCHDOG_SECONDS
    memory_ceiling_mb: int | None = None

    @classmethod
    def from_mapping(cls, path: str, data: dict[str, Any] | None) -> "ResourcePolicy":
        raw = _mapping_or_empty(path, data)
        _validate_keys(
            path,
            raw,
            {
                "idle_timeout_seconds",
                "cpu_watchdog_percent",
                "cpu_watchdog_seconds",
                "memory_ceiling_mb",
            },
        )
        idle_timeout_seconds = _positive_int(
            f"{path}.idle_timeout_seconds",
            raw.get("idle_timeout_seconds", DEFAULT_IDLE_TIMEOUT_SECONDS),
        )
        cpu_watchdog_percent = _bounded_int(
            f"{path}.cpu_watchdog_percent",
            raw.get("cpu_watchdog_percent", DEFAULT_CPU_WATCHDOG_PERCENT),
            minimum=1,
            maximum=100,
        )
        cpu_watchdog_seconds = _positive_int(
            f"{path}.cpu_watchdog_seconds",
            raw.get("cpu_watchdog_seconds", DEFAULT_CPU_WATCHDOG_SECONDS),
        )
        memory_ceiling_mb = _optional_positive_int(
            f"{path}.memory_ceiling_mb",
            raw.get("memory_ceiling_mb"),
        )
        return cls(
            idle_timeout_seconds=idle_timeout_seconds,
            cpu_watchdog_percent=cpu_watchdog_percent,
            cpu_watchdog_seconds=cpu_watchdog_seconds,
            memory_ceiling_mb=memory_ceiling_mb,
        )


@dataclass(frozen=True)
class AuthRepairPolicy:
    tool: str = ""
    arguments: dict[str, Any] | None = None
    trigger_errors: tuple[str, ...] = ()
    retry_original: bool = True
    timeout_seconds: int = DEFAULT_AUTH_REPAIR_TIMEOUT_SECONDS

    @classmethod
    def from_mapping(cls, path: str, data: dict[str, Any] | None) -> "AuthRepairPolicy | None":
        if data is None:
            return None
        raw = _mapping_or_empty(path, data)
        _validate_keys(
            path,
            raw,
            {"tool", "arguments", "trigger_errors", "retry_original", "timeout_seconds"},
        )
        tool = raw.get("tool")
        if not isinstance(tool, str) or not tool:
            raise ValueError(f"{path}.tool must be a non-empty string")
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError(f"{path}.arguments must be a mapping")
        trigger_errors = raw.get("trigger_errors", [])
        if not isinstance(trigger_errors, list) or not trigger_errors:
            raise ValueError(f"{path}.trigger_errors must be a non-empty list")
        if any(not isinstance(trigger, str) for trigger in trigger_errors):
            raise ValueError(f"{path}.trigger_errors must contain strings")
        parsed_triggers = tuple(trigger_errors)
        if any(not trigger for trigger in parsed_triggers):
            raise ValueError(f"{path}.trigger_errors cannot contain empty values")
        retry_original = raw.get("retry_original", True)
        if not isinstance(retry_original, bool):
            raise ValueError(f"{path}.retry_original must be a boolean")
        return cls(
            tool=tool,
            arguments=arguments,
            trigger_errors=parsed_triggers,
            retry_original=retry_original,
            timeout_seconds=_positive_int(
                f"{path}.timeout_seconds",
                raw.get("timeout_seconds", DEFAULT_AUTH_REPAIR_TIMEOUT_SECONDS),
            ),
        )


@dataclass(frozen=True)
class SmokeProbe:
    query: str
    tool: str
    arguments: dict[str, Any]
    call: bool = True

    @classmethod
    def from_mapping(cls, path: str, data: dict[str, Any] | None) -> "SmokeProbe | None":
        if data is None:
            return None
        raw = _mapping_or_empty(path, data)
        _validate_keys(path, raw, {"query", "tool", "arguments", "call"})
        query = raw.get("query")
        if not isinstance(query, str) or not query:
            raise ValueError(f"{path}.query must be a non-empty string")
        tool = raw.get("tool")
        if not isinstance(tool, str) or not tool:
            raise ValueError(f"{path}.tool must be a non-empty string")
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError(f"{path}.arguments must be a mapping")
        call = raw.get("call", True)
        if not isinstance(call, bool):
            raise ValueError(f"{path}.call must be a boolean")
        return cls(query=query, tool=tool, arguments=arguments, call=call)


def parse_profiles(path: str, data: Any) -> tuple[str, ...]:
    if data is None:
        return ("manual-test",)
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path} must be a non-empty list")
    profiles = tuple(str(profile) for profile in data)
    if any(not profile for profile in profiles):
        raise ValueError(f"{path} cannot contain empty values")
    return profiles


def parse_transport(path: str, value: Any) -> str:
    transport = str(value or "stdio")
    if transport not in ALLOWED_UPSTREAM_TRANSPORTS:
        allowed = ", ".join(sorted(ALLOWED_UPSTREAM_TRANSPORTS))
        raise ValueError(f"{path} must be one of: {allowed}")
    return transport


def parse_mode(path: str, value: Any) -> str:
    mode = str(value or "shared")
    if mode not in ALLOWED_UPSTREAM_MODES:
        allowed = ", ".join(sorted(ALLOWED_UPSTREAM_MODES))
        raise ValueError(f"{path} must be one of: {allowed}")
    return mode


def parse_startup_timeout(path: str, value: Any) -> int:
    return _positive_int(path, value or DEFAULT_STARTUP_TIMEOUT_SECONDS)


def _mapping_or_empty(path: str, data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    return data


def _validate_keys(path: str, data: dict[str, Any], allowed_keys: set[str]) -> None:
    for key in data:
        if key not in allowed_keys:
            raise ValueError(f"unknown config key: {path}.{key}")


def _positive_int(path: str, value: Any) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{path} must be greater than 0")
    return parsed


def _optional_positive_int(path: str, value: Any) -> int | None:
    if value is None:
        return None
    return _positive_int(path, value)


def _non_negative_int(path: str, value: Any) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{path} must be 0 or greater")
    return parsed


def _bounded_int(path: str, value: Any, *, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{path} must be between {minimum} and {maximum}")
    return parsed
