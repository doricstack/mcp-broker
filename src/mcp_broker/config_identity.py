"""Broker identity configuration and status payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_broker.config_keys import BROKER_IDENTITY_KEYS

CONFIG_SCHEMA_VERSION = 1
DEFAULT_BROKER_ID = "mcp-broker-local"
DEFAULT_BROKER_ENVIRONMENT = "local"
DEFAULT_BUNDLE_VERSION = "unbundled"


@dataclass(frozen=True)
class BrokerIdentityConfig:
    broker_id: str = DEFAULT_BROKER_ID
    environment: str = DEFAULT_BROKER_ENVIRONMENT
    bundle_version: str = DEFAULT_BUNDLE_VERSION

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "BrokerIdentityConfig":
        raw = {} if data is None else data
        if not isinstance(raw, dict):
            raise ValueError("broker.identity must be a mapping")
        _validate_identity_keys(raw)
        return cls(
            broker_id=_parse_non_empty_string(
                "broker.identity.broker_id",
                raw.get("broker_id", DEFAULT_BROKER_ID),
            ),
            environment=_parse_non_empty_string(
                "broker.identity.environment",
                raw.get("environment", DEFAULT_BROKER_ENVIRONMENT),
            ),
            bundle_version=_parse_non_empty_string(
                "broker.identity.bundle_version",
                raw.get("bundle_version", DEFAULT_BUNDLE_VERSION),
            ),
        )

    def status_payload(
        self,
        *,
        active_profile: str | None,
        active_profiles: list[str],
    ) -> dict[str, object]:
        return {
            "active_profile": active_profile,
            "active_profiles": active_profiles,
            "broker_id": self.broker_id,
            "bundle_version": self.bundle_version,
            "environment": self.environment,
            "schema_version": CONFIG_SCHEMA_VERSION,
        }


def default_identity_status_payload() -> dict[str, object]:
    return BrokerIdentityConfig().status_payload(
        active_profile=None,
        active_profiles=[],
    )


def _validate_identity_keys(data: dict[str, Any]) -> None:
    for key in data:
        if key not in BROKER_IDENTITY_KEYS:
            raise ValueError(f"unknown config key: broker.identity.{key}")


def _parse_non_empty_string(path: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value
