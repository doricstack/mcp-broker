from pathlib import Path
from io import BytesIO
import json
import os
import sys

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_client_shim_forwards_payload_to_broker_socket(tmp_path: Path) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'):
        response = ClientShim(socket_path=socket_path).forward_payload(
            b'{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
        )

    assert response == b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'


def test_client_shim_injects_profile_into_mcp_tool_requests(tmp_path: Path) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    client_cwd = str(Path.cwd())
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"list","result":{"tools":[]}}\n') as broker:
        response = ClientShim(
            socket_path=socket_path,
            profile="llm-profile",
            session_id="llm-session-a",
        ).forward_payload(
            b'{"jsonrpc":"2.0","id":"list","method":"tools/list"}\n'
        )

    assert response == b'{"jsonrpc":"2.0","id":"list","result":{"tools":[]}}\n'
    assert json.loads(broker.received.decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": "list",
        "method": "tools/list",
        "params": {
            "profile": "llm-profile",
            "broker_session_id": "llm-session-a",
            "broker_client_cwd": client_cwd,
        },
    }

    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"call","result":{"content":[]}}\n') as broker:
        ClientShim(
            socket_path=socket_path,
            profile="llm-profile",
            session_id="llm-session-a",
        ).forward_payload(
            b'{"jsonrpc":"2.0","id":"call","method":"tools/call",'
            b'"params":{"name":"broker.search_tools","arguments":{"query":"repo"}}}\n'
        )

    assert json.loads(broker.received.decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": "call",
        "method": "tools/call",
        "params": {
            "name": "broker.search_tools",
            "arguments": {"query": "repo"},
            "profile": "llm-profile",
            "broker_session_id": "llm-session-a",
            "broker_client_cwd": client_cwd,
        },
    }


def test_client_shim_preserves_existing_broker_client_cwd(tmp_path: Path) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    payload = (
        b'{"jsonrpc":"2.0","id":"call","method":"tools/call",'
        b'"params":{"name":"fake.echo","arguments":{},'
        b'"broker_client_cwd":"/tmp/client-project"}}\n'
    )
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"call","result":{}}\n') as broker:
        ClientShim(socket_path=socket_path, session_id="session-a").forward_payload(payload)

    assert json.loads(broker.received.decode("utf-8"))["params"]["broker_client_cwd"] == (
        "/tmp/client-project"
    )


def test_client_shim_injects_session_when_profile_is_explicit_or_absent(
    tmp_path: Path,
) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    client_cwd = str(Path.cwd())
    payload = (
        b'{"jsonrpc":"2.0","id":"list","method":"tools/list",'
        b'"params":{"profile":"maintenance"}}\n'
    )
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"list","result":{}}\n') as broker:
        ClientShim(
            socket_path=socket_path,
            profile="llm-profile",
            session_id="llm-session-b",
        ).forward_payload(payload)

    assert json.loads(broker.received.decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": "list",
        "method": "tools/list",
        "params": {
            "profile": "maintenance",
            "broker_session_id": "llm-session-b",
            "broker_client_cwd": client_cwd,
        },
    }

    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"call","result":{}}\n') as broker:
        ClientShim(socket_path=socket_path, session_id="llm-session-c").forward_payload(
            b'{"jsonrpc":"2.0","id":"call","method":"tools/call",'
            b'"params":{"name":"fake.echo","arguments":{}}}\n'
        )

    assert json.loads(broker.received.decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": "call",
        "method": "tools/call",
        "params": {
            "name": "fake.echo",
            "arguments": {},
            "broker_session_id": "llm-session-c",
            "broker_client_cwd": client_cwd,
        },
    }


def test_client_shim_preserves_existing_broker_session_and_omits_absent_profile(
    tmp_path: Path,
) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    payload = (
        b'{"jsonrpc":"2.0","id":"call","method":"tools/call",'
        b'"params":{"name":"fake.echo","arguments":{},"broker_session_id":"existing-session"}}\n'
    )
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"call","result":{}}\n') as broker:
        ClientShim(socket_path=socket_path, session_id="new-session").forward_payload(payload)

    assert json.loads(broker.received.decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": "call",
        "method": "tools/call",
        "params": {
            "name": "fake.echo",
            "arguments": {},
            "broker_session_id": "existing-session",
            "broker_client_cwd": str(Path.cwd()),
        },
    }

    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"list","result":{}}\n') as broker:
        ClientShim(socket_path=socket_path, session_id="session-only").forward_payload(
            b'{"jsonrpc":"2.0","id":"list","method":"tools/list"}\n'
        )

    assert json.loads(broker.received.decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": "list",
        "method": "tools/list",
        "params": {
            "broker_session_id": "session-only",
            "broker_client_cwd": str(Path.cwd()),
        },
    }


def test_client_shim_does_not_inject_profile_into_initialize(tmp_path: Path) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"init","result":{}}\n') as broker:
        ClientShim(socket_path=socket_path, profile="codex").forward_payload(
            b'{"jsonrpc":"2.0","id":"init","method":"initialize"}\n'
        )

    assert broker.received == b'{"jsonrpc":"2.0","id":"init","method":"initialize"}\n'


def test_client_shim_leaves_malformed_payloads_unchanged(
    tmp_path: Path,
) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"bad","result":{}}\n') as broker:
        ClientShim(socket_path=socket_path, profile="codex").forward_payload(b'{"bad-json"\n')

    assert broker.received == b'{"bad-json"\n'

    payload = b'{"jsonrpc":"2.0","id":"bad","method":"tools/call","params":[]}\n'
    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"bad","result":{}}\n') as broker:
        ClientShim(
            socket_path=socket_path,
            profile="llm-profile",
            session_id="llm-session-d",
        ).forward_payload(payload)

    assert broker.received == payload


def test_client_shim_reports_missing_broker_socket(tmp_path: Path) -> None:
    from mcp_broker.client import ClientShim, ClientShimError

    socket_path = tmp_path / "missing.sock"

    with pytest.raises(ClientShimError, match="broker socket unavailable"):
        ClientShim(socket_path=socket_path).forward_payload(b"{}\n")


def test_client_shim_maps_stale_socket_connect_errors(tmp_path: Path) -> None:
    from mcp_broker.client import ClientShim, ClientShimError

    socket_path = _socket_path(tmp_path)
    socket_path.write_text("stale", encoding="utf-8")

    try:
        with pytest.raises(ClientShimError, match="broker socket unavailable"):
            ClientShim(socket_path=socket_path).forward_payload(b"{}\n")
    finally:
        socket_path.unlink(missing_ok=True)


def test_client_shim_run_stdio_writes_broker_response(tmp_path: Path) -> None:
    from io import BytesIO

    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    stdin = BytesIO(b'{"jsonrpc":"2.0","id":"stdio","method":"initialize"}\n')
    stdout = BytesIO()

    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"stdio","result":{}}\n'):
        ClientShim(socket_path=socket_path).run_stdio(stdin, stdout)

    assert stdout.getvalue() == b'{"jsonrpc":"2.0","id":"stdio","result":{}}\n'


def test_client_shim_run_stdio_forwards_notifications_without_stdout_response(
    tmp_path: Path,
) -> None:
    from io import BytesIO

    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)
    stdin = BytesIO(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    stdout = BytesIO()

    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":null,"result":null}\n') as broker:
        ClientShim(socket_path=socket_path, profile="codex").run_stdio(stdin, stdout)

    assert broker.received == b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
    assert stdout.getvalue() == b""


def test_client_shim_treats_invalid_notification_payload_as_request() -> None:
    from mcp_broker.client import _is_jsonrpc_notification

    assert _is_jsonrpc_notification(b'{"jsonrpc":"2.0","method":') is False
    assert _is_jsonrpc_notification(b"\xff") is False


def test_client_main_returns_success_for_stdio_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.client import main

    socket_path = _socket_path(tmp_path)
    stdin = BinaryWrapper(b'{"jsonrpc":"2.0","id":"cli","method":"initialize"}\n')
    stdout = BinaryWrapper()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"cli","result":{}}\n'):
        result = main(["--socket-path", str(socket_path), "--profile", "llm"])

    assert result == 0
    assert stdout.buffer.getvalue() == b'{"jsonrpc":"2.0","id":"cli","result":{}}\n'


def test_client_main_reports_missing_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.client import main

    monkeypatch.setattr(sys, "stdin", BinaryWrapper(b'{"jsonrpc":"2.0","id":"cli"}\n'))
    monkeypatch.setattr(sys, "stdout", BinaryWrapper())

    result = main(["--socket-path", str(tmp_path / "missing.sock")])

    captured = capsys.readouterr()
    assert result == 1
    assert "broker socket unavailable" in captured.err


def test_client_main_expands_environment_in_socket_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.client import main

    home = Path("/tmp") / f"mcp-broker-client-home-{os.getpid()}"
    socket_path = home / "mcp" / "mcp-broker" / "sockets" / "broker.sock"
    socket_path.parent.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "stdin", BinaryWrapper(b'{"jsonrpc":"2.0","id":"cli"}\n'))
    monkeypatch.setattr(sys, "stdout", BinaryWrapper())

    with FakeBrokerSocket(socket_path, b'{"jsonrpc":"2.0","id":"cli","result":{"ok":true}}\n'):
        result = main(["--socket-path", "$HOME/mcp/mcp-broker/sockets/broker.sock"])

    assert result == 0


def test_client_shim_reads_response_until_socket_closes(tmp_path: Path) -> None:
    from mcp_broker.client import ClientShim

    socket_path = _socket_path(tmp_path)

    with FakeBrokerSocket(socket_path, b'{"partial":true}'):
        response = ClientShim(socket_path=socket_path).forward_payload(b"{}\n")

    assert response == b'{"partial":true}'


class FakeBrokerSocket:
    def __init__(self, socket_path: Path, response: bytes) -> None:
        import socket
        import threading

        self.socket_path = socket_path
        self.response = response
        self.received = b""
        self._socket_module = socket
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve)
        self._thread.daemon = True

    def __enter__(self) -> "FakeBrokerSocket":
        self._thread.start()
        self._ready.wait(timeout=2)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._thread.join(timeout=2)
        self.socket_path.unlink(missing_ok=True)

    def _serve(self) -> None:
        with self._socket_module.socket(
            self._socket_module.AF_UNIX,
            self._socket_module.SOCK_STREAM,
        ) as server:
            server.bind(str(self.socket_path))
            server.listen()
            self._ready.set()
            connection, _ = server.accept()
            with connection:
                self.received = connection.recv(4096)
                connection.sendall(self.response)


def _socket_path(tmp_path: Path) -> Path:
    import os

    return Path("/tmp") / f"mcp-broker-client-unit-{os.getpid()}-{tmp_path.name}.sock"


class BinaryWrapper:
    def __init__(self, data: bytes = b"") -> None:
        self.buffer = BytesIO(data)
