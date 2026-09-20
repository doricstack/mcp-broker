from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcp_broker.daemon import BrokerDaemon, _lock_holder_pid
from mcp_broker.daemon_errors import BrokerDaemonError


pytestmark = pytest.mark.unit


def _daemon(tmp_path: Path) -> BrokerDaemon:
    return BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")


def test_acquire_lock_records_own_pid_and_release_preserves_the_file(tmp_path: Path) -> None:
    daemon = _daemon(tmp_path)

    daemon._acquire_lock()
    try:
        assert json.loads(daemon.lock_path.read_text(encoding="utf-8")) == {
            "owner": "mcp-broker",
            "pid": os.getpid(),
        }
    finally:
        daemon._release_lock()

    assert daemon.lock_path.exists()


def test_acquire_lock_refuses_while_a_live_holder_owns_the_file(tmp_path: Path) -> None:
    holder = _daemon(tmp_path)
    contender = _daemon(tmp_path)
    holder._acquire_lock()
    try:
        with pytest.raises(BrokerDaemonError, match=f"already running: pid {os.getpid()}"):
            contender._acquire_lock()
    finally:
        holder._release_lock()


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"owner": "mcp-broker", "pid": 99_999_999}),
        # A truncated or hand-edited lock file must not be fatal either.
        "",
        "not json",
        "{}",
    ],
)
def test_acquire_lock_takes_a_file_no_live_holder_owns(tmp_path: Path, content: str) -> None:
    daemon = _daemon(tmp_path)
    daemon.lock_path.parent.mkdir(parents=True)
    daemon.lock_path.write_text(content, encoding="utf-8")

    daemon._acquire_lock()
    try:
        assert json.loads(daemon.lock_path.read_text(encoding="utf-8")) == {
            "owner": "mcp-broker",
            "pid": os.getpid(),
        }
    finally:
        daemon._release_lock()


def test_acquire_lock_takes_a_file_that_names_this_live_process(tmp_path: Path) -> None:
    """A live pid is not ownership: the kernel hands recycled numbers to anyone.

    Regression: after a reboot the pid recorded in a stale lock belonged to an
    unrelated running process, and every daemon start refused with "already
    running". Ownership now comes from the flock, so the recorded pid is free
    to be meaningless.
    """
    daemon = _daemon(tmp_path)
    daemon.lock_path.parent.mkdir(parents=True)
    daemon.lock_path.write_text(
        json.dumps({"owner": "mcp-broker", "pid": os.getpid()}), encoding="utf-8"
    )

    daemon._acquire_lock()
    try:
        assert json.loads(daemon.lock_path.read_text(encoding="utf-8")) == {
            "owner": "mcp-broker",
            "pid": os.getpid(),
        }
    finally:
        daemon._release_lock()


def test_lock_holder_pid_reports_the_recorded_pid(tmp_path: Path) -> None:
    lock_path = tmp_path / "broker.lock"
    lock_path.write_text(json.dumps({"owner": "mcp-broker", "pid": 4321}), encoding="utf-8")

    assert _lock_holder_pid(lock_path) == 4321


@pytest.mark.parametrize("content", ["", "not json", "{}", '{"pid": "not-a-number"}'])
def test_lock_holder_pid_degrades_to_unknown_on_unreadable_content(
    tmp_path: Path, content: str
) -> None:
    lock_path = tmp_path / "broker.lock"
    lock_path.write_text(content, encoding="utf-8")

    assert _lock_holder_pid(lock_path) == "unknown"


def test_lock_holder_pid_degrades_to_unknown_when_the_file_is_missing(tmp_path: Path) -> None:
    assert _lock_holder_pid(tmp_path / "absent.lock") == "unknown"
