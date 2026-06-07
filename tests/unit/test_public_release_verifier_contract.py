from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_public_release import (
    ReleaseVerificationConfig,
    ReleaseVerificationError,
    verify_public_release,
)


pytestmark = pytest.mark.unit


VERSION = "9.8.7"
MINOR_VERSION = "9.8"
GITHUB_REPO = "ExampleOrg/example-broker"
PYPI_PROJECT = "example-broker"
NPM_PACKAGE = "@example/example-broker"
DOCKER_NAMESPACE = "example"
DOCKER_IMAGE_NAME = "example-broker"
MCP_REGISTRY_NAME = "io.github.ExampleOrg/example-broker"
HOMEBREW_FORMULA_URL = "https://example.test/homebrew-tap/Formula/example-broker.rb"
GITHUB_RELEASE_URL = "https://api.example.test/repos/ExampleOrg/example-broker/releases/tags/v9.8.7"
PYPI_VERSION_URL = "https://pypi.example.test/pypi/example-broker/9.8.7/json"
NPM_REGISTRY_URL = "https://npm.example.test"
DOCKER_HUB_API_REPOSITORY_BASE_URL = "https://dockerhub.example.test/repositories"
DOCKER_REGISTRY_SERVICE = "registry.example.test"
DOCKER_REGISTRY_HOST = "docker.example.test"
DOCKER_REGISTRY_AUTH_URL = "https://docker-auth.example.test/token"
DOCKER_REGISTRY_MANIFEST_BASE_URL = "https://docker-registry.example.test/v2"
GHCR_REGISTRY_SERVICE = "ghcr.example.test"
GHCR_REGISTRY_HOST = "ghcr.example.test"
GHCR_REGISTRY_AUTH_URL = "https://ghcr-auth.example.test/token"
GHCR_REGISTRY_MANIFEST_BASE_URL = "https://ghcr-registry.example.test/v2"
MCP_REGISTRY_SEARCH_URL = "https://mcp-registry.example.test/servers?search=io.github.ExampleOrg/example-broker"


def _config() -> ReleaseVerificationConfig:
    return ReleaseVerificationConfig(
        version=VERSION,
        npm_package=NPM_PACKAGE,
        docker_namespace=DOCKER_NAMESPACE,
        docker_image_name=DOCKER_IMAGE_NAME,
        mcp_registry_name=MCP_REGISTRY_NAME,
        github_release_url=GITHUB_RELEASE_URL,
        pypi_version_url=PYPI_VERSION_URL,
        npm_registry_url=NPM_REGISTRY_URL,
        docker_hub_api_repository_base_url=DOCKER_HUB_API_REPOSITORY_BASE_URL,
        docker_registry_service=DOCKER_REGISTRY_SERVICE,
        docker_registry_host=DOCKER_REGISTRY_HOST,
        docker_registry_auth_url=DOCKER_REGISTRY_AUTH_URL,
        docker_registry_manifest_base_url=DOCKER_REGISTRY_MANIFEST_BASE_URL,
        ghcr_registry_service=GHCR_REGISTRY_SERVICE,
        ghcr_registry_host=GHCR_REGISTRY_HOST,
        ghcr_registry_auth_url=GHCR_REGISTRY_AUTH_URL,
        ghcr_registry_manifest_base_url=GHCR_REGISTRY_MANIFEST_BASE_URL,
        mcp_registry_search_url=MCP_REGISTRY_SEARCH_URL,
        homebrew_formula_url=HOMEBREW_FORMULA_URL,
    )


def test_public_release_verifier_checks_public_surface_versions() -> None:
    seen_json_urls: list[str] = []
    seen_text_urls: list[str] = []
    seen_manifests: list[str] = []

    def fetch_json(url: str) -> object:
        seen_json_urls.append(url)
        if url.endswith("/releases/tags/v9.8.7"):
            return {
                "tag_name": "v9.8.7",
                "draft": False,
                "prerelease": False,
                "html_url": "https://github.com/ExampleOrg/example-broker/releases/tag/v9.8.7",
            }
        if url.endswith("/pypi/example-broker/9.8.7/json"):
            return {"info": {"version": VERSION}}
        if url == "https://npm.example.test/%40example%2Fexample-broker":
            return {"dist-tags": {"latest": VERSION}, "versions": {VERSION: {}}}
        if url.endswith("/repositories/example/example-broker/"):
            return {"name": "example-broker", "namespace": "example", "is_private": False}
        if url.endswith("/repositories/example/example-broker/tags/9.8.7"):
            return {"name": VERSION}
        if url.endswith("/repositories/example/example-broker/tags/9.8"):
            return {"name": MINOR_VERSION}
        if url == MCP_REGISTRY_SEARCH_URL:
            return {
                "servers": [
                    {
                        "server": {
                            "name": MCP_REGISTRY_NAME,
                            "version": VERSION,
                        }
                    }
                ]
            }
        raise AssertionError(url)

    def fetch_text(url: str) -> str:
        seen_text_urls.append(url)
        return 'url "https://files.pythonhosted.org/packages/x/mcp_broker-9.8.7.tar.gz"'

    def manifest_exists(image: str, _config: ReleaseVerificationConfig) -> None:
        seen_manifests.append(image)

    verified = verify_public_release(
        _config(),
        fetch_json=fetch_json,
        fetch_text=fetch_text,
        manifest_exists=manifest_exists,
        checks={
            "github-release",
            "pypi",
            "npm",
            "docker-hub",
            "docker-registry",
            "ghcr",
            "mcp-registry",
            "homebrew",
        },
    )

    assert verified == [
        "github-release",
        "pypi",
        "npm",
        "docker-hub",
        "docker-registry",
        "ghcr",
        "mcp-registry",
        "homebrew",
    ]
    assert GITHUB_RELEASE_URL in seen_json_urls
    assert "https://dockerhub.example.test/repositories/example/example-broker/" in seen_json_urls
    assert "https://dockerhub.example.test/repositories/example/example-broker/tags/9.8.7" in seen_json_urls
    assert "https://dockerhub.example.test/repositories/example/example-broker/tags/9.8" in seen_json_urls
    assert f"{DOCKER_REGISTRY_HOST}/{DOCKER_NAMESPACE}/{DOCKER_IMAGE_NAME}:{VERSION}" in seen_manifests
    assert f"{GHCR_REGISTRY_HOST}/{DOCKER_NAMESPACE}/{DOCKER_IMAGE_NAME}:{VERSION}" in seen_manifests
    assert seen_text_urls == [HOMEBREW_FORMULA_URL]


def test_public_release_verifier_fails_when_docker_hub_is_not_public() -> None:
    def fetch_json(url: str) -> object:
        if url.endswith("/repositories/example/example-broker/"):
            raise OSError("HTTP 404")
        return {"name": VERSION}

    with pytest.raises(ReleaseVerificationError, match="Docker Hub repository is not public"):
        verify_public_release(
            _config(),
            fetch_json=fetch_json,
            fetch_text=lambda _url: "",
            manifest_exists=lambda _image, _config: None,
            checks={"docker-hub"},
        )


def test_public_release_verifier_uses_logging_instead_of_print() -> None:
    script = Path("scripts/verify_public_release.py").read_text(encoding="utf-8")

    assert "import logging" in script
    assert "LOGGER = logging.getLogger" in script
    assert "print(" not in script
