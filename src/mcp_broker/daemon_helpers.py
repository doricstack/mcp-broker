"""Daemon helper functions kept separate from the socket lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Mapping

from mcp_broker.broker import BrokerToolError
from mcp_broker.config import UpstreamConfig
from mcp_broker.upstream_stdio import StdioUpstreamProcess


SENSITIVE_LOG_KEY_PARTS = (
    "access_id",
    "api_key",
    "authorization",
    "credential",
    "env",
    "password",
    "secret",
    "token",
)


def health_profile(request: dict[str, object]) -> str:
    params = request.get("params")
    if isinstance(params, dict) and isinstance(params.get("profile"), str):
        return params["profile"]
    return "default"


def configured_upstream_health(upstream: UpstreamConfig) -> dict[str, object]:
    state = "disabled" if not upstream.enabled or upstream.mode == "disabled" else "configured"
    return {
        "state": state,
        "pid": None,
        "cpu_percent": None,
        "memory_mb": None,
        "restarts": 0,
        "last_error": None,
    }


def passive_auth_probe(
    upstream: UpstreamConfig,
    *,
    environ: Mapping[str, str],
) -> dict[str, object]:
    if not upstream.enabled or upstream.mode == "disabled":
        return {"auth_probe": "none"}
    missing_sources: list[str] = []
    for source_name in upstream.env.values():
        if not environ.get(source_name):
            missing_sources.append(f"env:{source_name}")
    for target_name, secret_path in upstream.env_files.items():
        if not _secret_file_has_value(secret_path):
            missing_sources.append(f"secret_file:{target_name}")
    if missing_sources:
        return {
            "auth_probe": "credentials_missing",
            "auth_state": "unauthenticated",
            "last_error": (
                f"missing auth source for upstream {upstream.name}: "
                f"{', '.join(missing_sources)}"
            ),
        }
    if upstream.env or upstream.env_files or upstream.request_meta:
        return {"auth_probe": "credentials_present"}
    if upstream.auth_repair is not None:
        return {"auth_probe": "auth_repair_configured"}
    return {"auth_probe": "none"}


def _secret_file_has_value(secret_path: object) -> bool:
    if not hasattr(secret_path, "read_text"):
        return False
    try:
        value = secret_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return value.rstrip("\r\n") != ""


def stdio_client_key(upstream: UpstreamConfig, *, session_id: str | None) -> str | tuple[str, str]:
    if upstream.mode == "per_session":
        if not session_id:
            raise BrokerToolError(
                code="missing_session",
                message=f"broker_session_id is required for per_session upstream: {upstream.name}",
                upstream_name=upstream.name,
            )
        return (upstream.name, session_id)
    return upstream.name


def stdio_client_name(key: str | tuple[str, str]) -> str:
    if isinstance(key, tuple):
        return f"{key[0]}:{key[1]}"
    return key


def per_session_health_snapshot(clients: list[StdioUpstreamProcess]) -> dict[str, object]:
    snapshots = [client.health_snapshot() for client in clients]
    states = [snapshot.get("state") for snapshot in snapshots]
    errors = [
        snapshot.get("last_error")
        for snapshot in snapshots
        if snapshot.get("last_error") is not None
    ]
    restart_total = sum(
        restart
        for snapshot in snapshots
        if isinstance((restart := snapshot.get("restarts")), int)
    )
    return {
        "state": "running" if "running" in states else str(states[0]),
        "pid": None,
        "cpu_percent": None,
        "memory_mb": None,
        "restarts": restart_total,
        "last_error": errors[0] if errors else None,
        "sessions": len(clients),
    }


def result_matches_auth_repair(upstream: UpstreamConfig, result: dict[str, object]) -> bool:
    repair = upstream.auth_repair
    if repair is None:
        return False
    text = _result_content_text(result)
    if not text:
        return False
    if result.get("isError") is not True and not text.startswith("Error:"):
        return False
    return any(trigger in text for trigger in repair.trigger_errors)


def redact_log_field(key: str, value: object) -> object:
    normalized = key.lower().replace("-", "_")
    if any(part in normalized for part in SENSITIVE_LOG_KEY_PARTS):
        return "[redacted]"
    return redact_log_value(value)


def redact_log_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): redact_log_field(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_log_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_log_value(item) for item in value]
    if isinstance(value, str):
        if "://" in value:
            return "[redacted:url]"
        if looks_like_filesystem_path(value):
            return "[redacted:path]"
    return value


def looks_like_filesystem_path(value: str) -> bool:
    return value.startswith(("/", "~/", "$HOME/", "${HOME}/")) or "/Users/" in value


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _result_content_text(result: dict[str, object]) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)
