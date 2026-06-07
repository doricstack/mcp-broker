"""Sync declared upstream secrets from the environment into the runtime secrets store.

Upstreams that resolve credentials via ``env_files`` read them from files under the
runtime secrets store (``<runtime-root>/secrets``). Those files survive the empty
environment that launchd hands the daemon, unlike ``env`` sources. This module
populates that store in one shot: for every ``env_files`` path that lives under the
secrets store, it reads the matching variable from the current shell environment
(store filename equals the environment variable name) and writes it with mode 0600.

It is best-effort by design. A variable missing from the environment is reported and
skipped, not treated as fatal, so a partial environment still syncs what it can.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Mapping, Protocol

from mcp_broker.config import BrokerConfig

logger = logging.getLogger(__name__)

_SECRET_FILE_MODE = 0o600


class _RuntimeLike(Protocol):
    @property
    def secrets_dir(self) -> Path: ...


class _UpstreamLike(Protocol):
    @property
    def env_files(self) -> Mapping[str, Path]: ...


class _ConfigLike(Protocol):
    @property
    def runtime(self) -> _RuntimeLike: ...

    @property
    def upstreams(self) -> Mapping[str, _UpstreamLike]: ...


def collect_secret_targets(config: _ConfigLike) -> dict[str, Path]:
    """Map environment variable name -> store path for store-managed ``env_files``.

    Only ``env_files`` paths that live under the configured secrets directory are
    managed here; paths pointing elsewhere are owned by the user and left untouched.
    The store filename is the environment variable name to read.
    """
    secrets_dir = config.runtime.secrets_dir.resolve()
    targets: dict[str, Path] = {}
    for upstream in config.upstreams.values():
        for raw_store_path in upstream.env_files.values():
            store_path = raw_store_path.resolve()
            try:
                store_path.relative_to(secrets_dir)
            except ValueError:
                continue
            targets[store_path.name] = store_path
    return targets


def sync_secrets(
    config: _ConfigLike,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Write present secrets to the store; report missing ones. Returns (imported, skipped)."""
    env = os.environ if environ is None else environ
    targets = collect_secret_targets(config)
    imported: list[str] = []
    skipped: list[str] = []
    for name, store_path in sorted(targets.items()):
        value = env.get(name)
        if not value:
            skipped.append(name)
            continue
        store_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(store_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _SECRET_FILE_MODE)
        try:
            os.write(fd, (value.rstrip("\r\n") + "\n").encode())
        finally:
            os.close(fd)
        os.chmod(store_path, _SECRET_FILE_MODE)
        imported.append(name)
    return imported, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to the broker config file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = BrokerConfig.from_file(Path(args.config))
    imported, skipped = sync_secrets(config)
    logger.info(
        "secrets sync: imported %d, skipped %d (missing from environment)",
        len(imported),
        len(skipped),
    )
    if skipped:
        logger.info("not in environment, store unchanged: %s", ", ".join(skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
