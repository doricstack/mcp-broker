import subprocess
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_broker import __version__
from mcp_broker import daemon as daemon_module
from mcp_broker import daemon_provenance as daemon_provenance_module
from mcp_broker.daemon import _git_sha, _source_provenance


pytestmark = pytest.mark.unit


def test_source_provenance_reports_package_path_and_version() -> None:
    provenance = _source_provenance()

    assert provenance["version"] == __version__
    assert provenance["source_path"].endswith("mcp_broker")
    assert Path(provenance["source_path"]).is_absolute()


def test_git_sha_returns_none_outside_a_repo(tmp_path: Path) -> None:
    assert _git_sha(tmp_path) is None


def test_git_sha_resolves_inside_a_repo(tmp_path: Path) -> None:
    # Build a real repo so the test is independent of how the source tree was
    # obtained (a mutation/CI container copies source without a .git dir).
    git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [*git, "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    sha = _git_sha(tmp_path)

    assert sha is not None
    assert len(sha) >= 7


@pytest.mark.error_simulation
def test_git_sha_returns_none_when_git_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*args: object, **kwargs: object) -> object:
        raise OSError("git binary not found")

    monkeypatch.setattr(daemon_provenance_module.subprocess, "run", _raise)

    assert _git_sha(tmp_path) is None


@pytest.mark.error_simulation
def test_source_provenance_omits_git_sha_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daemon_module, "_git_sha", lambda _source: None)

    provenance = _source_provenance()

    assert "git_sha" not in provenance
    assert provenance["version"] == __version__


@pytest.mark.error_simulation
def test_source_provenance_includes_resolved_git_sha_for_the_package_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def _fake_git_sha(source: Path) -> str:
        seen["source"] = source
        return "deadbee"

    monkeypatch.setattr(daemon_module, "_git_sha", _fake_git_sha)

    provenance = _source_provenance()

    assert provenance["git_sha"] == "deadbee"
    # The sha is resolved for the package's own source dir, not some other path.
    assert seen["source"] == Path(daemon_module.__file__).resolve().parent


@pytest.mark.error_simulation
def test_git_sha_invokes_git_with_exact_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _fake_run(cmd: object, **kwargs: object) -> object:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="abc1234\n")

    monkeypatch.setattr(daemon_provenance_module.subprocess, "run", _fake_run)

    result = _git_sha(tmp_path)

    assert captured["cmd"] == ["git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["timeout"] == 2
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    # stdout is stripped of the trailing newline.
    assert result == "abc1234"


@pytest.mark.error_simulation
def test_git_sha_returns_none_for_whitespace_only_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        daemon_provenance_module.subprocess,
        "run",
        lambda cmd, **kwargs: SimpleNamespace(stdout="  \n"),
    )

    assert _git_sha(tmp_path) is None
