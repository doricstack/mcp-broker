import os
import time
from pathlib import Path

import pytest

from mcp_broker.upstream_process import _start_drainer


pytestmark = pytest.mark.unit


def test_process_output_drainer_flushes_log_before_pipe_closes(tmp_path: Path) -> None:
    read_fd, write_fd = os.pipe()
    log_path = tmp_path / "stdout.log"
    read_pipe = os.fdopen(read_fd, "rb", buffering=0)
    thread = _start_drainer(read_pipe, log_path)

    try:
        os.write(write_fd, b"visible-before-close\n")
        deadline = time.monotonic() + 1
        while (
            "visible-before-close" not in _read_if_exists(log_path)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert "visible-before-close" in log_path.read_text(encoding="utf-8")
    finally:
        os.close(write_fd)
        thread.join(timeout=1)


def _read_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
