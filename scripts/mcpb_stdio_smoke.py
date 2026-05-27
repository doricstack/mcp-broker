from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import subprocess
from typing import Any


LOGGER = logging.getLogger(__name__)
REQUESTS = (
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "mcpb-stdio-smoke", "version": "0"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
)


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("MCPB manifest must be a JSON object")
    return manifest


def build_command(
    *,
    manifest: dict[str, Any],
    command_override: str | None,
    runtime_root: str,
    socket_path: str,
    config_path: str,
    profile: str,
    uvx_path: str,
) -> list[str]:
    mcp_config = manifest.get("server", {}).get("mcp_config")
    if not isinstance(mcp_config, dict):
        raise ValueError("MCPB manifest missing server.mcp_config")
    command = str(mcp_config.get("command") or "")
    args = mcp_config.get("args")
    if not command or not isinstance(args, list):
        raise ValueError("MCPB manifest server.mcp_config must contain command and args")
    values = {
        "uvx_path": uvx_path,
        "runtime_root": runtime_root,
        "socket_path": socket_path,
        "config_path": config_path,
        "profile": profile,
    }
    resolved_command = _substitute(command, values)
    resolved_args = [_substitute(str(arg), values) for arg in args]
    if command_override:
        resolved_command = command_override
        if resolved_args[:1] == ["mcp-broker"]:
            resolved_args = resolved_args[1:]
    return [resolved_command, *resolved_args]


def run_smoke(command: list[str], timeout_seconds: int) -> None:
    stdin = "".join(json.dumps(request, separators=(",", ":")) + "\n" for request in REQUESTS)
    result = subprocess.run(
        command,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "MCPB stdio command failed with exit "
            f"{result.returncode}\nstderr:\n{result.stderr}\nstdout:\n{result.stdout}"
        )
    responses = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip().startswith("{")
    ]
    if not any(
        isinstance(response.get("result"), dict)
        and isinstance(response["result"].get("tools"), list)
        for response in responses
        if isinstance(response, dict)
    ):
        raise RuntimeError(f"MCPB stdio command did not return tools/list: {result.stdout}")


def _substitute(value: str, replacements: dict[str, str]) -> str:
    resolved = value
    for key, replacement in replacements.items():
        resolved = resolved.replace("${user_config." + key + "}", replacement)
    return resolved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test an MCPB stdio command.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--command", help="Command override for source-tree smoke")
    parser.add_argument("--uvx-path", default="uvx")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", default="claude")
    parser.add_argument("--timeout-seconds", type=int, default=25)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = load_manifest(args.manifest)
    command = build_command(
        manifest=manifest,
        command_override=args.command,
        runtime_root=args.runtime_root,
        socket_path=args.socket_path,
        config_path=args.config,
        profile=args.profile,
        uvx_path=args.uvx_path,
    )
    run_smoke(command, args.timeout_seconds)
    LOGGER.info("MCPB stdio smoke passed: %s", command[0])
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
