"""Socket framing, cumulative limits, and persisted error accounting."""

import json
from pathlib import Path

import pytest

from mcp_broker.daemon import BrokerDaemon
from mcp_broker.daemon_errors import BrokerRequestTooLarge
from mcp_broker.daemon_socket import read_request, send_response


pytestmark = pytest.mark.unit


class ChunkedConnection:
    """Return bounded fragments without depending on OS packet coalescing."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.read_sizes: list[int] = []
        self.sent = b""

    def recv(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) > size:
            self.chunks.insert(0, chunk[size:])
        return chunk[:size]

    def sendall(self, data: bytes) -> None:
        self.sent += data


def test_read_request_accepts_exact_limit_and_preserves_fragment_bytes() -> None:
    connection = ChunkedConnection([b"ab", b"cd", b"\n", b"unread"])

    assert read_request(connection, max_bytes=5, chunk_bytes=2) == b"abcd\n"
    assert connection.read_sizes == [2, 2, 2]
    assert connection.chunks == [b"unread"]


def test_read_request_rejects_cumulative_limit_before_reading_more() -> None:
    connection = ChunkedConnection([b"ab", b"cd", b"e\n", b"unread"])

    with pytest.raises(BrokerRequestTooLarge) as caught:
        read_request(connection, max_bytes=5, chunk_bytes=2)

    assert str(caught.value) == "Request exceeds 5 bytes"
    assert connection.read_sizes == [2, 2, 2]
    assert connection.chunks == [b"unread"]


def test_send_response_uses_sorted_json_and_one_line_terminator() -> None:
    connection = ChunkedConnection([])
    response = {"result": {"z": "caf\u00e9", "a": "line\nbreak"}, "id": 7}

    send_response(connection, response)

    assert connection.sent == (
        b'{"id": 7, "result": {"a": "line\\nbreak", "z": "caf\\u00e9"}}\n'
    )
    assert connection.sent.count(b"\n") == 1
    assert json.loads(connection.sent) == response


def test_handle_connection_preserves_a_raw_utf8_request_id(tmp_path: Path) -> None:
    daemon = BrokerDaemon(runtime_root=tmp_path, socket_path=tmp_path / "broker.sock")
    connection = ChunkedConnection([b' {"id":"caf\xc3\xa9","method":"unknown"} \n'])

    assert daemon._handle_connection(connection) is None

    assert json.loads(connection.sent) == {"id": "caf\u00e9", "error": {"code": "unknown_method"}}
    assert connection.sent == b'{"error": {"code": "unknown_method"}, "id": "caf\\u00e9"}\n'
    snapshot = json.loads(daemon.status_snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["requests_total"] == 1
    assert snapshot["request_errors_total"] == 1


@pytest.mark.parametrize(
    ("payload", "limit", "code", "message"),
    [
        (b'{"id":', 64, -32700, "Parse error"),
        (b"123456\n", 5, -32600, "Request exceeds 5 bytes"),
    ],
)
def test_connection_errors_are_persisted_as_errors(
    tmp_path: Path, payload: bytes, limit: int, code: int, message: str
) -> None:
    daemon = BrokerDaemon(runtime_root=tmp_path, socket_path=tmp_path / "broker.sock")
    daemon._socket_max_request_bytes = limit
    connection = ChunkedConnection([payload])

    daemon._handle_connection(connection)

    assert json.loads(connection.sent) == {
        "jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}
    }
    snapshot = json.loads(daemon.status_snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["requests_total"] == 1
    assert snapshot["request_errors_total"] == 1
    assert snapshot["last_request_status"] == "error"
    records = [json.loads(line) for line in daemon.log_path.read_text(encoding="utf-8").splitlines()]
    assert [(row["event"], row["status"], row["request_id"], row["method"]) for row in records] == [
        ("request.handled", "error", None, None)
    ]
