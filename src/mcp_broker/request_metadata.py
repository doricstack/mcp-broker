"""Call-scoped metadata; never retain caller context on a cached client."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from mcp_broker.config_keys import ENV_NAME_PATTERN, META_NAME_PATTERN

_current: ContextVar[Mapping[str, Any]] = ContextVar("request_metadata", default={})


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
