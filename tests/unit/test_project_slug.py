"""Unit tests for cwd -> project-slug injection (codebase-memory ergonomics).

The broker auto-fills the `project` arg for upstreams that require an indexed
slug (codebase-memory), derived from the caller's cwd, so an LLM never has to
error-then-retry to discover it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import mcp_broker.project_slug as project_slug_module
from mcp_broker.project_slug import derive_project_slug, inject_cwd_project


pytestmark = pytest.mark.unit


def test_derive_slug_from_repo_root(tmp_path):
    repo = tmp_path / "Projects" / "apps" / "demo"
    (repo / ".git").mkdir(parents=True)
    slug = derive_project_slug(str(repo))
    assert slug == str(repo).lstrip("/").replace("/", "-")


def test_derive_slug_walks_up_to_git_root(tmp_path):
    repo = tmp_path / "apps" / "demo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "backend" / "scripts"
    sub.mkdir(parents=True)
    # called from a subdir -> resolves to the repo root slug, not the subdir
    assert derive_project_slug(str(sub)) == str(repo).lstrip("/").replace("/", "-")


def test_derive_slug_no_git_falls_back_to_cwd(tmp_path):
    d = tmp_path / "loose"
    d.mkdir()
    assert derive_project_slug(str(d)) == str(d).lstrip("/").replace("/", "-")


@pytest.mark.error_simulation
def test_derive_slug_falls_back_when_git_probe_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    original_exists = Path.exists

    def exists_or_raise(path: Path) -> bool:
        if path.name == ".git":
            raise OSError("permission denied")
        return original_exists(path)

    d = tmp_path / "locked"
    d.mkdir()
    monkeypatch.setattr(Path, "exists", exists_or_raise)

    assert derive_project_slug(str(d)) == str(d).lstrip("/").replace("/", "-")


@pytest.mark.error_simulation
def test_derive_slug_handles_zero_walk_limit(monkeypatch: pytest.MonkeyPatch, tmp_path):
    d = tmp_path / "no-walk"
    d.mkdir()
    monkeypatch.setattr(project_slug_module, "_MAX_WALK", 0)

    assert derive_project_slug(str(d)) == str(d).lstrip("/").replace("/", "-")


def test_derive_slug_rejects_relative():
    assert derive_project_slug("relative/path") is None
    assert derive_project_slug("") is None


def _repo(tmp_path):
    repo = tmp_path / "apps" / "demo"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_inject_adds_project_when_missing(tmp_path):
    repo = _repo(tmp_path)
    out = inject_cwd_project(
        "codebase-memory.get_graph_schema", {}, str(repo),
        tool_prefix="codebase-memory", separator=".", exclude=frozenset(),
    )
    assert out["project"] == str(repo).lstrip("/").replace("/", "-")


def test_inject_respects_caller_supplied_project(tmp_path):
    out = inject_cwd_project(
        "codebase-memory.search_graph", {"project": "Users-nba-Projects-apps-other"},
        str(_repo(tmp_path)), tool_prefix="codebase-memory", separator=".", exclude=frozenset(),
    )
    assert out["project"] == "Users-nba-Projects-apps-other"   # unchanged


def test_inject_skips_excluded_tool(tmp_path):
    out = inject_cwd_project(
        "codebase-memory.list_projects", {}, str(_repo(tmp_path)),
        tool_prefix="codebase-memory", separator=".", exclude=frozenset({"list_projects"}),
    )
    assert "project" not in out


def test_inject_ignores_other_upstreams(tmp_path):
    out = inject_cwd_project(
        "github.create_issue", {"title": "x"}, str(_repo(tmp_path)),
        tool_prefix="codebase-memory", separator=".", exclude=frozenset(),
    )
    assert out == {"title": "x"}   # prefix mismatch -> untouched


def test_inject_skips_when_no_cwd(tmp_path):
    out = inject_cwd_project(
        "codebase-memory.search_graph", {}, None,
        tool_prefix="codebase-memory", separator=".", exclude=frozenset(),
    )
    assert "project" not in out


def test_inject_treats_empty_project_as_missing(tmp_path):
    repo = _repo(tmp_path)
    out = inject_cwd_project(
        "codebase-memory.search_graph", {"project": "  "}, str(repo),
        tool_prefix="codebase-memory", separator=".", exclude=frozenset(),
    )
    assert out["project"] == str(repo).lstrip("/").replace("/", "-")
