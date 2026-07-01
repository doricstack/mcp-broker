"""Request context helpers mixed into the broker daemon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_broker.config import BrokerConfig
from mcp_broker.daemon_helpers import health_profile as _health_profile
from mcp_broker.profiles import ToolExposureProfile, select_profile_for_cwd
from mcp_broker.project_slug import inject_cwd_project


class BrokerDaemonRequestContextMixin:
    broker_config: BrokerConfig | None

    def _inject_cwd_project_arg(
        self, name: str, arguments: dict[str, Any], session_context: dict[str, str]
    ) -> dict[str, Any]:
        if self.broker_config is None:
            return arguments
        client_cwd = session_context.get("client_cwd")
        if not client_cwd:
            return arguments
        separator = self.broker_config.broker.tool_namespace_separator or "."
        for upstream in self.broker_config.upstreams.values():
            if not upstream.inject_cwd_project:
                continue
            arguments = inject_cwd_project(
                name,
                arguments,
                client_cwd,
                tool_prefix=upstream.tool_prefix or upstream.name,
                separator=separator,
                exclude=upstream.inject_cwd_project_exclude,
            )
        return arguments

    def _profile_from_params(self, params: object) -> ToolExposureProfile | None:
        if not isinstance(params, dict) or params.get("profile") is None:
            return None
        if self.broker_config is None:
            return None
        profile_name = params.get("profile")
        if not isinstance(profile_name, str):
            raise ValueError("profile must be a string")
        profile = self.broker_config.profiles.get(profile_name)
        if profile is None:
            raise ValueError(f"unknown profile: {profile_name}")
        return profile

    def _effective_profile(
        self,
        params: object,
        session_context: dict[str, str],
    ) -> ToolExposureProfile | None:
        requested = self._profile_from_params(params)
        if self.broker_config is None:
            return requested
        return select_profile_for_cwd(
            self.broker_config.profiles,
            requested,
            session_context.get("client_cwd"),
        )

    def _effective_profile_name(self, request: dict[str, object]) -> str:
        params = request.get("params")
        try:
            session_context = self._session_context_from_params(params)
            profile = self._effective_profile(params, session_context)
        except ValueError:
            return _health_profile(request)
        if profile is not None:
            return profile.name
        return _health_profile(request)

    def _session_id_from_params(self, params: object) -> str | None:
        if not isinstance(params, dict):
            return None
        session_id = params.get("broker_session_id")
        if session_id is None:
            meta = params.get("_meta")
            if isinstance(meta, dict):
                broker_meta = meta.get("mcp_broker")
                if isinstance(broker_meta, dict):
                    session_id = broker_meta.get("session_id")
        if session_id is None:
            return None
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("broker_session_id must be a non-empty string")
        return session_id

    def _session_context_from_params(self, params: object) -> dict[str, str]:
        if not isinstance(params, dict):
            return {}
        client_cwd = params.get("broker_client_cwd")
        if client_cwd is None:
            meta = params.get("_meta")
            if isinstance(meta, dict):
                broker_meta = meta.get("mcp_broker")
                if isinstance(broker_meta, dict):
                    client_cwd = broker_meta.get("client_cwd")
        if client_cwd is None:
            return {}
        if not isinstance(client_cwd, str) or not client_cwd:
            raise ValueError("broker_client_cwd must be a non-empty string")
        if not Path(client_cwd).is_absolute():
            raise ValueError("broker_client_cwd must be an absolute path")
        return {"client_cwd": client_cwd}
