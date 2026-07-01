"""Source provenance helpers for daemon startup logging."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess


def git_sha(source_dir: Path) -> str | None:
    """Best-effort short git SHA of the source tree, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha or None


def source_provenance(
    source_path: Path,
    version: str,
    *,
    git_sha_fn: Callable[[Path], str | None] = git_sha,
) -> dict[str, str]:
    """Identify which source tree and version this daemon is running."""
    provenance = {"source_path": str(source_path), "version": version}
    sha = git_sha_fn(source_path)
    if sha is not None:
        provenance["git_sha"] = sha
    return provenance
