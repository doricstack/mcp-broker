"""Call-scoped metadata; never retain caller context on a cached client."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from mcp_broker.config_keys import ENV_NAME_PATTERN, META_NAME_PATTERN

_current: ContextVar[Mapping[str, Any]] = ContextVar("request_metadata", default={})
# Metadata the broker itself adds to every forwarded tools/call, such as the
# active profile's result budget. Callers cannot set or override it.
_broker: ContextVar[Mapping[str, Any]] = ContextVar("broker_request_metadata", default={})

RESULT_BUDGET_META_KEY = "mcp-broker/result_budget_chars"


@contextmanager
def request_metadata_scope(params: object) -> Iterator[None]:
    metadata = params.get("_meta", {}) if isinstance(params, dict) else {}
    if not isinstance(metadata, dict):
        raise ValueError("tools/call _meta must be an object")
    token = _current.set(metadata)
    try:
        yield
    finally:
        _current.reset(token)


def forwarded_request_metadata(names: tuple[str, ...]) -> dict[str, Any]:
    """Copy only administrator-approved fields from the current request."""
    metadata = _current.get()
    return {name: deepcopy(metadata[name]) for name in names if name in metadata}


@contextmanager
def broker_request_metadata_scope(metadata: Mapping[str, Any]) -> Iterator[None]:
    token = _broker.set(dict(metadata))
    try:
        yield
    finally:
        _broker.reset(token)


def broker_request_metadata() -> dict[str, Any]:
    """Return the broker-owned metadata for the current call."""
    return deepcopy(dict(_broker.get()))


def outbound_request_metadata(names: tuple[str, ...]) -> dict[str, Any]:
    """Approved caller fields, then broker-owned fields, which take precedence."""
    metadata = forwarded_request_metadata(names)
    metadata.update(broker_request_metadata())
    return metadata


def result_budget_metadata(profile: Any) -> dict[str, Any]:
    """Map a profile's result_budget_chars onto the upstream _meta field."""
    budget = getattr(profile, "result_budget_chars", None)
    if budget is None:
        return {}
    return {RESULT_BUDGET_META_KEY: budget}


def parse_request_meta(
    path: str, value: Any, *, configured_env_names: set[str],
) -> dict[str, str]:
    """Validate administrator-supplied metadata credential mappings."""
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a mapping")
    parsed: dict[str, str] = {}
    for meta_name, source_name in value.items():
        if not isinstance(meta_name, str) or not META_NAME_PATTERN.fullmatch(meta_name):
            raise ValueError(f"{path} keys must be request metadata names")
        if not isinstance(source_name, str) or not ENV_NAME_PATTERN.match(source_name):
            raise ValueError(f"{path}.{meta_name} must name a configured environment variable")
        if source_name not in configured_env_names:
            raise ValueError(f"{path}.{meta_name} must reference env or env_files")
        parsed[meta_name] = source_name
    return parsed
