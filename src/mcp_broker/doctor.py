"""Runtime doctor checks for mcp-broker config and upstream commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from typing import Sequence

from mcp_broker.config import BrokerConfig


@dataclass(frozen=True)
class BrokenUpstreamCommand:
    upstream_name: str
    command: str


def find_broken_upstream_commands(config: BrokerConfig) -> tuple[BrokenUpstreamCommand, ...]:
    broken: list[BrokenUpstreamCommand] = []
    for upstream_name, upstream in sorted(config.upstreams.items()):
        if not upstream.enabled or upstream.mode == "disabled":
            continue
        if upstream.transport != "stdio":
            continue
        if _command_available(upstream.command):
            continue
        broken.append(BrokenUpstreamCommand(upstream_name=upstream_name, command=upstream.command))
    return tuple(broken)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate mcp-broker runtime config")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = BrokerConfig.from_file(Path(args.config))
    broken = find_broken_upstream_commands(config)
    for item in broken:
        sys.stderr.write(f"broken upstream command: {item.upstream_name}: {item.command}\n")
    return 1 if broken else 0


def _command_available(command: str) -> bool:
    if "/" not in command:
        return shutil.which(command) is not None
    path = Path(command).expanduser()
    return path.is_file() and os.access(path, os.X_OK)


if __name__ == "__main__":
    raise SystemExit(main())
