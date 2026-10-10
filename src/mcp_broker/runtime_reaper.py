"""Runtime cleanup for broker-owned process and socket metadata."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Sequence


OWNER = "mcp-broker"

# Overridable so a test can present a fixture proc tree instead of the host's.
_PROC_ROOT = Path("/proc")


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
            # Liveness alone is not ownership. The kernel recycles pids, so a
            # recycled broker pid hides a real orphan from the kill below, and a
            # recycled upstream pid keeps a dead upstream's pidfile alive
            # forever. Both are checked against the identity recorded at spawn.
            broker_alive = _pid_still_owns_metadata(
                broker_pid, _recorded_identity(metadata, "broker_start_time")
            )
            if not broker_alive and _process_group_exists(process_group_id):
                _kill_process_group(process_group_id)
                metadata_path.unlink(missing_ok=True)
                killed_orphans.append(name)
            elif not _pid_still_owns_metadata(
                pid, _recorded_identity(metadata, "start_time")
            ):
                metadata_path.unlink(missing_ok=True)
                stale_pidfiles.append(name)

        for metadata_path in sorted(self.paths.socket_owner_dir.glob("*.json")):
            metadata = _read_metadata(metadata_path)
            if metadata.get("owner") != OWNER:
                continue
            socket_name = str(metadata["socket_name"])
            pid = int(metadata["pid"])
            if _pid_still_owns_metadata(
                pid, _recorded_identity(metadata, "start_time")
            ):
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
            # Identity, so the next startup reaps this record if the kernel has
            # since handed either pid to another process. Null means the
            # platform could not say, and the reaper falls back to liveness.
            "start_time": process_start_time(pid),
            "broker_start_time": process_start_time(broker_pid),
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
            "start_time": process_start_time(pid),
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


def _linux_start_time(pid: int) -> str | None:
    """Field 22 of `/proc/<pid>/stat`, the process start time in clock ticks."""
    try:
        stat = (_PROC_ROOT / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        # The command name is parenthesised and may itself contain spaces and
        # parentheses, so the fields after it start at the last closing paren.
        fields = stat[stat.rindex(")") + 2 :].split()
        return fields[19]
    except (ValueError, IndexError):
        return None


def _darwin_start_time(pid: int) -> str | None:
    """`ps -o lstart=` for the pid, which Darwin exposes no proc tree for."""
    try:
        done = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def process_start_time(pid: int) -> str | None:
    """A value that changes when the kernel hands this pid to another process.

    Identity, not liveness. `_process_exists` answers "is this number in use",
    which stops being the same question once the kernel recycles it: a stale
    pidfile naming a dead upstream can outlive it through any unrelated process
    that inherits the number. That is what took the broker down on 2026-09-18.

    None means the platform could not answer. Callers keep the old
    liveness-only behaviour in that case rather than guessing, so a host
    without a proc tree degrades to the previous semantics instead of
    destroying live runtime state.
    """
    if pid <= 0:
        return None
    reader = _linux_start_time if sys.platform == "linux" else _darwin_start_time
    return reader(pid)


def _recorded_identity(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _pid_still_owns_metadata(pid: int, recorded: str | None) -> bool:
    """True while `pid` is the process the metadata was written about.

    Legacy metadata carries no identity. It is trusted on liveness alone, which
    is exactly what the metadata written from here on does better, and refusing
    to act on it would leave the old files unreapable forever.
    """
    if not _process_exists(pid):
        return False
    if recorded is None:
        return True
    live = process_start_time(pid)
    if live is None:
        return True
    return live == recorded


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
