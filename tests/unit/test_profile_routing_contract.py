from pathlib import Path

import pytest

from mcp_broker.profiles import (
    ClientRootMatch,
    ToolExposureProfile,
    select_profile_for_cwd,
)


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def _apps(tmp_path: Path) -> Path:
    apps = tmp_path / "Projects" / "apps"
    (apps / "genai-quiz-pro" / "backend").mkdir(parents=True)
    (apps / "genai-quiz-pro-android").mkdir(parents=True)
    (apps / "forte").mkdir(parents=True)
    (tmp_path / "elsewhere" / "genai-quiz-pro").mkdir(parents=True)
    return apps


def _match(apps: Path) -> ClientRootMatch:
    return ClientRootMatch(parent=apps, name_prefix="genai-quiz-pro")


def test_match_root_dir_itself(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    assert _match(apps).matches(str(apps / "genai-quiz-pro")) is True


def test_match_subdirectory_of_root(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    assert _match(apps).matches(str(apps / "genai-quiz-pro" / "backend")) is True


def test_match_sibling_by_name_prefix(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    assert _match(apps).matches(str(apps / "genai-quiz-pro-android")) is True


def test_no_match_for_non_prefixed_sibling(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    assert _match(apps).matches(str(apps / "forte")) is False


def test_no_match_when_parent_is_not_apps_dir(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    spoof = tmp_path / "elsewhere" / "genai-quiz-pro"
    assert _match(apps).matches(str(spoof)) is False


def test_no_match_for_missing_cwd(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    assert _match(apps).matches(None) is False
    assert _match(apps).matches("") is False


def test_no_match_when_client_cwd_cannot_be_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apps = _apps(tmp_path)

    def fail_resolve(self: Path) -> Path:
        raise OSError(f"cannot resolve {self}")

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    assert _match(apps).matches(str(apps / "genai-quiz-pro")) is False


def _profiles(apps: Path) -> dict[str, ToolExposureProfile]:
    claude = ToolExposureProfile(name="claude", max_tools=80, compact_tools_enabled=True)
    bfai = ToolExposureProfile(
        name="bfai",
        max_tools=120,
        compact_tools_enabled=True,
        client_root_match=_match(apps),
    )
    return {"claude": claude, "bfai": bfai}


def test_routes_to_bfai_for_matching_cwd(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    profiles = _profiles(apps)
    effective = select_profile_for_cwd(profiles, profiles["claude"], str(apps / "genai-quiz-pro"))
    assert effective is not None and effective.name == "bfai"


def test_routes_to_bfai_for_matching_sibling_cwd(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    profiles = _profiles(apps)
    effective = select_profile_for_cwd(
        profiles, profiles["claude"], str(apps / "genai-quiz-pro-android")
    )
    assert effective is not None and effective.name == "bfai"


def test_keeps_requested_profile_for_non_matching_cwd(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    profiles = _profiles(apps)
    effective = select_profile_for_cwd(profiles, profiles["claude"], str(apps / "forte"))
    assert effective is not None and effective.name == "claude"


def test_keeps_requested_profile_when_cwd_absent(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    profiles = _profiles(apps)
    effective = select_profile_for_cwd(profiles, profiles["claude"], None)
    assert effective is not None and effective.name == "claude"


def test_returns_requested_when_no_routed_profile_defined() -> None:
    claude = ToolExposureProfile(name="claude", max_tools=80, compact_tools_enabled=True)
    profiles = {"claude": claude}
    effective = select_profile_for_cwd(profiles, claude, "/tmp")
    assert effective is not None and effective.name == "claude"


def test_none_requested_stays_none_when_no_match(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    profiles = _profiles(apps)
    assert select_profile_for_cwd(profiles, None, str(apps / "forte")) is None


def test_parse_client_root_match_from_mapping(tmp_path: Path) -> None:
    apps = _apps(tmp_path)
    profile = ToolExposureProfile.from_mapping(
        "bfai",
        {
            "max_tools": 120,
            "compact_tools_enabled": True,
            "broker_tool_name_style": "snake",
            "client_root_match": {"parent": str(apps), "name_prefix": "genai-quiz-pro"},
        },
    )
    assert profile.client_root_match is not None
    assert profile.client_root_match.matches(str(apps / "genai-quiz-pro")) is True


def test_parse_rejects_relative_parent() -> None:
    with pytest.raises(ValueError):
        ToolExposureProfile.from_mapping(
            "bfai",
            {"max_tools": 120, "client_root_match": {"parent": "relative/dir", "name_prefix": "x"}},
        )


def test_parse_rejects_non_mapping_client_root_match() -> None:
    with pytest.raises(ValueError, match="client_root_match must be a mapping"):
        ToolExposureProfile.from_mapping("bfai", {"max_tools": 120, "client_root_match": []})


def test_parse_rejects_missing_parent() -> None:
    with pytest.raises(ValueError, match="client_root_match.parent is required"):
        ToolExposureProfile.from_mapping(
            "bfai",
            {"max_tools": 120, "client_root_match": {"name_prefix": "genai-quiz-pro"}},
        )


def test_parse_rejects_empty_name_prefix(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ToolExposureProfile.from_mapping(
            "bfai",
            {"max_tools": 120, "client_root_match": {"parent": str(tmp_path), "name_prefix": ""}},
        )


def test_direct_client_root_match_rejects_empty_name_prefix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="client_root_match.name_prefix cannot be empty"):
        ClientRootMatch(parent=tmp_path, name_prefix="")
