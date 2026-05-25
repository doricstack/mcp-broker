"""JSON-RPC 2.0 request and response primitives."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


@dataclass(frozen=True)
class JsonRpcRequest:
    method: str
    id: str | int | None = None
    params: dict[str, Any] | list[Any] | None = None
    has_id: bool = False

    @classmethod
    def from_json(cls, payload: str) -> "JsonRpcRequest":
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid json-rpc payload") from exc
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data: Any) -> "JsonRpcRequest":
        if isinstance(data, list):
            raise ValueError("json-rpc batches are not supported")
        if not isinstance(data, dict):
            raise ValueError("json-rpc payload must be an object")
        if data.get("jsonrpc") != "2.0":
            raise ValueError("jsonrpc must be 2.0")
        method = data.get("method")
        if not isinstance(method, str) or not method:
            raise ValueError("method is required")
        params = data.get("params")
        if params is not None and not isinstance(params, (dict, list)):
            raise ValueError("params must be object or array")
        return cls(
            method=method,
            id=data.get("id"),
            params=params,
            has_id="id" in data,
        )

    @property
    def is_notification(self) -> bool:
        return not self.has_id


@dataclass(frozen=True, init=False)
class JsonRpcResponse:
    id: str | int | None
    result: JsonValue = None
    error: dict[str, Any] | None = None

    def __init__(
        self,
        *,
        id: str | int | None,
        result: JsonValue = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "error", error)

    @classmethod
    def result(cls, request_id: str | int | None, result: JsonValue) -> "JsonRpcResponse":
        return cls(id=request_id, result=result)

    @classmethod
    def error(
        cls,
        request_id: str | int | None,
        code: int,
        message: str,
    ) -> "JsonRpcResponse":
        return cls(
            id=request_id,
            error={"code": code, "message": message},
        )

    def to_mapping(self) -> dict[str, Any]:
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.error is None:
            response["result"] = self.result
            return response
        response["error"] = self.error
        return response

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), separators=(",", ":"), sort_keys=True)
