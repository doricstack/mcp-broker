"""Status snapshots and structured logging for the broker daemon."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from mcp_broker.config_identity import default_identity_status_payload
from mcp_broker.daemon_helpers import (
    redact_log_field as _redact_log_field,
    utc_timestamp as _utc_timestamp,
)


_DEFAULT_LOG_LEVEL = "info"


class BrokerDaemonStatusMixin:
    @property
    def log_path(self) -> Path:
        return self._paths.root / "logs" / "broker.jsonl"

    @property
    def status_snapshot_path(self) -> Path:
        if self.broker_config is None:
            return self._paths.root / "state" / "broker-status.json"
        return self.broker_config.runtime.state_dir / "broker-status.json"

    def _write_request_log(
        self,
        request_id: object,
        method: object,
        response: dict[str, object] | None,
    ) -> None:
        status = "notification" if response is None else "error" if "error" in response else "ok"
        self._requests_total += 1
        if status == "error":
            self._request_errors_total += 1
        self._last_request_method = method if isinstance(method, str) else None
        self._last_request_status = status
        self._write_log(
            "request.handled",
            method=self._last_request_method,
            request_id=request_id if isinstance(request_id, str | int | float | bool) else None,
            status=status,
        )
        self._write_status_snapshot("running")

    def _write_request_log_safely(
        self,
        request_id: object,
        method: object,
        response: dict[str, object] | None,
    ) -> None:
        try:
            self._write_request_log(request_id, method, response)
        except Exception as exc:
            self._write_log("request.log_failed", level="error", error=str(exc))

    def _write_log(self, event: str, *, level: str | None = None, **fields: object) -> None:
        record = {
            "event": event,
            "level": level if level is not None else _DEFAULT_LOG_LEVEL,
            "pid": os.getpid(),
            "ts": _utc_timestamp(),
        } | {key: _redact_log_field(key, value) for key, value in fields.items()}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    def _write_upstream_event(
        self,
        event: str,
        upstream_name: str,
        fields: dict[str, object],
    ) -> None:
        self._write_log(event, upstream=upstream_name, **fields)

    def _write_status_snapshot(self, status: str) -> None:
        if self.broker_config is None:
            identity = default_identity_status_payload()
        else:
            identity = self.broker_config.identity_status_payload(active_profile=None)
        snapshot = {
            "identity": identity,
            "last_request_method": self._last_request_method,
            "last_request_status": self._last_request_status,
            "pid": os.getpid(),
            "request_errors_total": self._request_errors_total,
            "requests_total": self._requests_total,
            "socket_path": str(self.socket_path),
            "started_at": self._started_at,
            "status": status,
            "updated_at": _utc_timestamp(),
            "upstreams": self._upstream_health(restart_upstreams=set()),
        }
        path = self.status_snapshot_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._status_snapshot_lock:
            tmp_path = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
            tmp_path.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
            tmp_path.replace(path)
