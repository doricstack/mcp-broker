"""Derive an indexed project slug from the caller's cwd and inject it as the
`project` argument for upstreams that require it (codebase-memory).

Why: codebase-memory tools require a `project` slug (the absolute repo path with
the leading "/" dropped and every "/" replaced by "-"). LLMs routinely omit it,
get an error that echoes the right slug, and retry - one wasted round-trip every
call. The broker already knows the caller's cwd (`broker_client_cwd`), so it can
fill the slug in on the first call. Caller-supplied `project` is always respected.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

_MAX_WALK = 64


def derive_project_slug(client_cwd: str | None) -> str | None:
    """Repo-root slug for `client_cwd`: walk up to the nearest `.git`, then
    slugify that path (leading "/" dropped, "/" -> "-"). Falls back to the cwd
    slug if no `.git` is found. Returns None for empty/relative paths."""
    if not client_cwd:
        return None
    p = Path(client_cwd)
    if not p.is_absolute():
        return None
    root = p
    cur = p
    for _ in range(_MAX_WALK):
        try:
            if (cur / ".git").exists():
                root = cur
                break
        except OSError:
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return str(root).lstrip("/").replace("/", "-")


def inject_cwd_project(
    name: str,
    arguments: dict[str, Any],
    client_cwd: str | None,
    *,
    tool_prefix: str,
    separator: str,
    exclude: Iterable[str],
) -> dict[str, Any]:
    """Return `arguments` with `project` filled from `client_cwd` when:
    the tool belongs to `tool_prefix`, is not in `exclude`, `project` is missing
    or blank, and a slug can be derived. Otherwise returns `arguments` unchanged."""
    prefix = f"{tool_prefix}{separator}"
    if not name.startswith(prefix):
        return arguments
    short = name[len(prefix):]
    if short in set(exclude):
        return arguments
    existing = arguments.get("project")
    if isinstance(existing, str) and existing.strip():
        return arguments
    slug = derive_project_slug(client_cwd)
    if not slug:
        return arguments
    return {**arguments, "project": slug}
