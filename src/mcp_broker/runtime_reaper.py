"""Runtime cleanup for broker-owned process and socket metadata."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import sys
from typing import Sequence


OWNER = "mcp-broker"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @classmethod
    def from_root(cls, root: Path) -> "RuntimePaths":
        return cls(root=root)

    @property
    def run_dir(self) -> Path:
        return self.root / "run"

    @property
    def sockets_dir(self) -> Path:
        return self.root / "sockets"

    @property
    def upstream_pid_dir(self) -> Path:
        return self.run_dir / "upstreams"

    @property
    def socket_owner_dir(self) -> Path:
        return self.run_dir / "sockets"

    def ensure(self) -> None:
        for path in [
            self.root / "logs",
            self.root / "secrets",
            self.root / "state" / "upstreams",
            self.run_dir,
            self.sockets_dir,
            self.upstream_pid_dir,
            self.socket_owner_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ReapReport:
    stale_pidfiles: tuple[str, ...] = ()
    killed_orphans: tuple[str, ...] = ()
    stale_sockets: tuple[str, ...] = ()


class RuntimeReaper:
    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def reap(self) -> ReapReport:
        self.paths.ensure()
        stale_pidfiles: list[str] = []
        killed_orphans: list[str] = []
        stale_sockets: list[str] = []

        for metadata_path in sorted(self.paths.upstream_pid_dir.glob("*.json")):
            metadata = _read_metadata(metadata_path)
            if metadata.get("owner") != OWNER:
                continue
            name = str(metadata["name"])
            pid = int(metadata["pid"])
            broker_pid = int(metadata.get("broker_pid", pid))
            process_group_id = int(metadata.get("process_group_id", pid))
            if not _process_exists(broker_pid) and _process_group_exists(process_group_id):
                _kill_process_group(process_group_id)
                metadata_path.unlink(missing_ok=True)
                killed_orphans.append(name)
            elif not _process_exists(pid):
                metadata_path.unlink(missing_ok=True)
                stale_pidfiles.append(name)

        for metadata_path in sorted(self.paths.socket_owner_dir.glob("*.json")):
            metadata = _read_metadata(metadata_path)
            if metadata.get("owner") != OWNER:
                continue
            socket_name = str(metadata["socket_name"])
            pid = int(metadata["pid"])
            if _process_exists(pid):
                continue
            socket_path = self.paths.sockets_dir / socket_name
            socket_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            stale_sockets.append(socket_name)

        return ReapReport(
            stale_pidfiles=tuple(stale_pidfiles),
            killed_orphans=tuple(killed_orphans),
            stale_sockets=tuple(stale_sockets),
        )


def write_process_metadata(
    paths: RuntimePaths,
    *,
    name: str,
    pid: int,
    process_group_id: int,
    broker_pid: int,
) -> Path:
    paths.ensure()
    metadata_path = paths.upstream_pid_dir / f"{name}.json"
    _write_metadata(
        metadata_path,
        {
            "owner": OWNER,
            "process_group_id": process_group_id,
            "pid": pid,
            "name": name,
            "broker_pid": broker_pid,
        },
    )
    return metadata_path


def write_socket_metadata(
    paths: RuntimePaths,
    *,
    socket_name: str,
    pid: int,
    broker_pid: int,
) -> Path:
    paths.ensure()
    metadata_path = paths.socket_owner_dir / f"{socket_name}.json"
    _write_metadata(
        metadata_path,
        {
            "socket_name": socket_name,
            "pid": pid,
            "owner": OWNER,
            "broker_pid": broker_pid,
        },
    )
    return metadata_path


def format_report(report: ReapReport) -> list[str]:
    lines: list[str] = []
    if report.stale_pidfiles:
        lines.append(f"reaped stale pidfiles: {', '.join(report.stale_pidfiles)}")
    if report.killed_orphans:
        lines.append(f"killed orphan process groups: {', '.join(report.killed_orphans)}")
    if report.stale_sockets:
        lines.append(f"removed stale sockets: {', '.join(report.stale_sockets)}")
    if not lines:
        lines.append("runtime reaper found no stale broker-owned resources")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reap mcp-broker runtime leftovers")
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args(argv)
    report = RuntimeReaper(RuntimePaths.from_root(Path(args.runtime_root))).reap()
    for line in format_report(report):
        sys.stdout.write(f"{line}\n")
    return 0


def _read_metadata(metadata_path: Path) -> dict[str, object]:
    return json.loads(metadata_path.read_bytes())


def _write_metadata(metadata_path: Path, payload: dict[str, object]) -> None:
    metadata_path.write_bytes(f"{json.dumps(payload, sort_keys=True)}\n".encode())


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_process_group(process_group_id: int) -> None:
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
