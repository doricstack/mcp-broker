"""Upstream lifecycle states."""

from __future__ import annotations

from enum import Enum


class UpstreamState(str, Enum):
    CONFIGURED = "configured"
    STARTING = "starting"
    RUNNING = "running"
    DRAINING = "draining"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    BACKOFF = "backoff"
    DISABLED = "disabled"
