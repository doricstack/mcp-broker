from pathlib import Path

import pytest

from mcp_broker.daemon import BrokerDaemon
from mcp_broker.daemon_errors import BrokerDaemonError

pytestmark = pytest.mark.unit


def test_release_preserves_inode_and_cannot_release_another_owner(tmp_path: Path) -> None:
    first = BrokerDaemon(runtime_root=tmp_path, socket_path=tmp_path / "broker.sock")
    second = BrokerDaemon(runtime_root=tmp_path, socket_path=tmp_path / "broker.sock")
    third = BrokerDaemon(runtime_root=tmp_path, socket_path=tmp_path / "broker.sock")
    first._acquire_lock()
    inode = first.lock_path.stat().st_ino
    first._release_lock()
    assert first.lock_path.exists()
    assert first.lock_path.stat().st_ino == inode
    second._acquire_lock()
    try:
        first._release_lock()
        assert second.lock_path.stat().st_ino == inode
        with pytest.raises(BrokerDaemonError, match="already running"):
            third._acquire_lock()
        third._release_lock()
        with pytest.raises(BrokerDaemonError, match="already running"):
            first._acquire_lock()
    finally:
        second._release_lock()
    third._acquire_lock()
    try:
        assert third.lock_path.stat().st_ino == inode
    finally:
        third._release_lock()
