import uuid
from pathlib import Path

import pytest

from mcp_broker.daemon import BrokerDaemon


pytestmark = pytest.mark.live


def _socket_path() -> Path:
    return Path("/tmp") / f"mcp-broker-janitor-{uuid.uuid4().hex}.sock"


def test_janitor_thread_starts_with_daemon_and_stops_cleanly(tmp_path: Path) -> None:
    daemon = BrokerDaemon(
        runtime_root=tmp_path / "runtime",
        socket_path=_socket_path(),
    )
    daemon.start()
    try:
        assert daemon._janitor_thread is not None
        assert daemon._janitor_thread.is_alive()
    finally:
        daemon.stop()

    assert daemon._janitor_thread is None
