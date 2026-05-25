#!/usr/bin/env python3
"""Copy public-safe files into a clean public checkout."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from fnmatch import fnmatch
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PRIVATE_MARKERS = [
    re.compile(pattern)
    for pattern in [
        r"/Users/[A-Za-z0-9._-]+/",
        r"\$HOME/Projects/",
        r"CloudStorage/",
        r"SESSION_HISTORY_ARCHIVE",
        r"PROJECT_CONTEXT\.md",
        r"docs/plans/",
        r"linkedin-context-management-brief",
    ]
]

SECRET_MARKERS = [
    re.compile(pattern)
    for pattern in [
        r"sk-(?:proj-|ant-|live_)[A-Za-z0-9_-]+",
        r"gh[pousr]_[A-Za-z0-9_]+",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ]
]

PRIVATE_MARKER_EXEMPT_PATHS = {
    "public-export/allowlist.txt",
    "public-export/denylist.txt",
    "scripts/public-export.py",
}

REQUIRED_PUBLIC_DOCS = [
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "ROADMAP.md",
]


@dataclass(frozen=True)
class ExportReport:
    copied: list[str]
    deleted: list[str]
    public_repo: Path

    def to_jsonable(self) -> dict[str, object]:
        return {
            "copied": self.copied,
            "deleted": self.deleted,
            "public_repo": str(self.public_repo),
        }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = export_public_repo(
            repo_root=args.repo_root,
            public_repo=args.public_repo,
            allowlist_path=args.allowlist,
            denylist_path=args.denylist,
            delete_stale=not args.no_delete_stale,
        )
    except ValueError as exc:
        sys.stderr.write(f"public-export failed: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(report.to_jsonable(), sort_keys=True) + "\n")
    return 0


def export_public_repo(
    *,
    repo_root: Path,
    public_repo: Path,
    allowlist_path: Path,
    denylist_path: Path,
    delete_stale: bool,
) -> ExportReport:
    repo_root = repo_root.expanduser().resolve()
    public_repo = public_repo.expanduser().resolve()
    if repo_root == public_repo:
        raise ValueError("public repo must not be the private repo root")

    allow_patterns = _load_patterns(allowlist_path)
    deny_patterns = _load_patterns(denylist_path)
    candidates = _tracked_or_local_files(repo_root)
    selected = [
        path
        for path in candidates
        if _matches_any(path, allow_patterns) and not _matches_any(path, deny_patterns)
    ]

    _validate_required_docs(selected)
    _scan_selected_files(repo_root, selected)

    public_repo.mkdir(parents=True, exist_ok=True)
    deleted = _delete_stale(public_repo, selected) if delete_stale else []
    copied = _copy_files(repo_root, public_repo, selected)
    return ExportReport(copied=sorted(copied), deleted=sorted(deleted), public_repo=public_repo)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export public-safe mcp-broker files")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Private repo root")
    parser.add_argument("--public-repo", type=Path, required=True, help="Public checkout path")
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path("public-export/allowlist.txt"),
        help="Allowlist file with exact paths or glob patterns",
    )
    parser.add_argument(
        "--denylist",
        type=Path,
        default=Path("public-export/denylist.txt"),
        help="Denylist file with exact paths or glob patterns",
    )
    parser.add_argument("--no-delete-stale", action="store_true", help="Do not delete stale public files")
    return parser.parse_args(argv)


def _load_patterns(path: Path) -> list[str]:
    patterns = []
    for raw_line in path.expanduser().read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _tracked_or_local_files(repo_root: Path) -> list[str]:
    if (repo_root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
        )
        return sorted(path for path in result.stdout.decode("utf-8").split("\0") if path)
    files = []
    for path in repo_root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            files.append(path.relative_to(repo_root).as_posix())
    return sorted(files)


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(path == pattern or fnmatch(path, pattern) for pattern in patterns)


def _validate_required_docs(selected: Sequence[str]) -> None:
    selected_set = set(selected)
    missing = [path for path in REQUIRED_PUBLIC_DOCS if path not in selected_set]
    if missing:
        raise ValueError(f"missing required public docs: {', '.join(missing)}")


def _scan_selected_files(repo_root: Path, selected: Sequence[str]) -> None:
    for relative in selected:
        text = (repo_root / relative).read_text(encoding="utf-8", errors="ignore")
        if relative not in PRIVATE_MARKER_EXEMPT_PATHS:
            for marker in PRIVATE_MARKERS:
                if marker.search(text):
                    raise ValueError(f"private marker in {relative}: {marker.pattern}")
        for marker in SECRET_MARKERS:
            if marker.search(text):
                raise ValueError(f"secret marker in {relative}: {marker.pattern}")


def _delete_stale(public_repo: Path, selected: Sequence[str]) -> list[str]:
    selected_set = set(selected)
    deleted = []
    for path in sorted(public_repo.rglob("*"), reverse=True):
        if ".git" in path.parts:
            continue
        if path.is_file():
            relative = path.relative_to(public_repo).as_posix()
            if relative not in selected_set:
                path.unlink()
                deleted.append(relative)
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return deleted


def _copy_files(repo_root: Path, public_repo: Path, selected: Sequence[str]) -> list[str]:
    copied = []
    for relative in selected:
        source = repo_root / relative
        destination = public_repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(relative)
    return copied


if __name__ == "__main__":
    raise SystemExit(main())
