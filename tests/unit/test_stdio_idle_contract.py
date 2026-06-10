import sys
from pathlib import Path

import pytest

from mcp_broker.config import UpstreamConfig
from mcp_broker.upstream_stdio import StdioUpstreamProcess


pytestmark = pytest.mark.unit


def _client(tmp_path: Path) -> StdioUpstreamProcess:
    return StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "runtime-state",
    )


def test_idle_seconds_measures_against_last_activity(tmp_path: Path) -> None:
    client = _client(tmp_path)

    client.record_activity(monotonic_seconds=100.0)

    assert client.idle_seconds(now=130.0) == 30.0


def test_record_activity_resets_the_idle_clock(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.record_activity(monotonic_seconds=100.0)

    client.record_activity(monotonic_seconds=200.0)

    assert client.idle_seconds(now=205.0) == 5.0


def test_fresh_client_starts_with_a_nonnegative_idle(tmp_path: Path) -> None:
    client = _client(tmp_path)

    # Construction stamps activity, so a brand-new client is never instantly stale.
    assert client.idle_seconds() >= 0.0
    assert client.idle_seconds(now=client._last_activity_monotonic + 7.0) == 7.0
