#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import json
import logging
import sys
import urllib.parse
import urllib.request


LOGGER = logging.getLogger(__name__)

CHECK_ORDER = [
    "github-release",
    "pypi",
    "npm",
    "docker-hub",
    "docker-registry",
    "ghcr",
    "mcp-registry",
    "homebrew",
]


class ReleaseVerificationError(ValueError):
    """Raised when one or more public release surfaces do not match."""


@dataclass(frozen=True)
class ReleaseVerificationConfig:
    version: str
    npm_package: str
    docker_namespace: str
    docker_image_name: str
    mcp_registry_name: str
    github_release_url: str
    pypi_version_url: str
    npm_registry_url: str
    docker_hub_api_repository_base_url: str
    docker_registry_service: str
    docker_registry_host: str
    docker_registry_auth_url: str
    docker_registry_manifest_base_url: str
    ghcr_registry_service: str
    ghcr_registry_host: str
    ghcr_registry_auth_url: str
    ghcr_registry_manifest_base_url: str
    mcp_registry_search_url: str
    homebrew_formula_url: str

    @property
    def minor_version(self) -> str:
        parts = self.version.split(".")
        if len(parts) < 2:
            return self.version
        return ".".join(parts[:2])

    @property
    def github_release_tag(self) -> str:
        return f"v{self.version}"


JsonFetcher = Callable[[str], object]
TextFetcher = Callable[[str], str]
ManifestChecker = Callable[[str, ReleaseVerificationConfig], None]


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers=_request_headers(url))
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _fetch_json(url: str) -> object:
    return json.loads(_fetch_text(url))


def _request_headers(url: str) -> dict[str, str]:
    return {"Accept": "application/json"}


def _expect_dict(value: object, surface: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{surface} response was not a JSON object")
    return value


def _verify_github_release(config: ReleaseVerificationConfig, fetch_json: JsonFetcher) -> None:
    try:
        payload = _expect_dict(fetch_json(config.github_release_url), "GitHub Release")
    except Exception as exc:
        raise ReleaseVerificationError(
            f"GitHub Release is not public: {config.github_release_tag}"
        ) from exc
    if payload.get("tag_name") != config.github_release_tag:
        raise ReleaseVerificationError(
            f"GitHub Release tag mismatch: expected {config.github_release_tag}"
        )
    if payload.get("draft") is not False:
        raise ReleaseVerificationError(f"GitHub Release is still a draft: {config.github_release_tag}")
    if payload.get("prerelease") is not False:
        raise ReleaseVerificationError(
            f"GitHub Release is marked prerelease: {config.github_release_tag}"
        )


def _verify_pypi(config: ReleaseVerificationConfig, fetch_json: JsonFetcher) -> None:
    try:
        payload = _expect_dict(fetch_json(config.pypi_version_url), "PyPI")
    except Exception as exc:
        raise ReleaseVerificationError(f"PyPI version is not public: {config.version}") from exc
    info = _expect_dict(payload.get("info"), "PyPI info")
    if info.get("version") != config.version:
        raise ReleaseVerificationError(f"PyPI version mismatch: expected {config.version}")


def _verify_npm(config: ReleaseVerificationConfig, fetch_json: JsonFetcher) -> None:
    quoted = urllib.parse.quote(config.npm_package, safe="")
    url = f"{config.npm_registry_url.rstrip('/')}/{quoted}"
    try:
        payload = _expect_dict(fetch_json(url), "NPM")
    except Exception as exc:
        raise ReleaseVerificationError(f"NPM package is not public: {config.npm_package}") from exc
    versions = _expect_dict(payload.get("versions"), "NPM versions")
    dist_tags = _expect_dict(payload.get("dist-tags"), "NPM dist-tags")
    if config.version not in versions:
        raise ReleaseVerificationError(f"NPM version is not public: {config.version}")
    if dist_tags.get("latest") != config.version:
        raise ReleaseVerificationError(f"NPM latest tag mismatch: expected {config.version}")


def _verify_docker_hub(config: ReleaseVerificationConfig, fetch_json: JsonFetcher) -> None:
    base = (
        f"{config.docker_hub_api_repository_base_url.rstrip('/')}/"
        f"{config.docker_namespace}/{config.docker_image_name}"
    )
    try:
        repo_payload = _expect_dict(fetch_json(f"{base}/"), "Docker Hub repository")
    except Exception as exc:
        raise ReleaseVerificationError(
            f"Docker Hub repository is not public: {config.docker_namespace}/{config.docker_image_name}"
        ) from exc
    if repo_payload.get("is_private") is True:
        raise ReleaseVerificationError(
            f"Docker Hub repository is private: {config.docker_namespace}/{config.docker_image_name}"
        )
    for tag in (config.version, config.minor_version):
        try:
            tag_payload = _expect_dict(fetch_json(f"{base}/tags/{tag}"), "Docker Hub tag")
        except Exception as exc:
            raise ReleaseVerificationError(f"Docker Hub tag is not public: {tag}") from exc
        if tag_payload.get("name") != tag:
            raise ReleaseVerificationError(f"Docker Hub tag mismatch: expected {tag}")


def _parse_image(
    image: str,
    *,
    default_registry_host: str,
    official_registry_host: str,
) -> tuple[str, str, str]:
    if ":" not in image.rsplit("/", maxsplit=1)[-1]:
        raise ReleaseVerificationError(f"Image tag is required: {image}")
    name, tag = image.rsplit(":", maxsplit=1)
    parts = name.split("/", maxsplit=1)
    if len(parts) == 2 and (
        "." in parts[0] or ":" in parts[0] or parts[0] == official_registry_host
    ):
        registry, repository = parts
    else:
        registry, repository = default_registry_host, name
    if registry == official_registry_host and "/" not in repository:
        repository = f"library/{repository}"
    return registry, repository, tag


def _verify_manifest_public(image: str, config: ReleaseVerificationConfig) -> None:
    registry, repository, tag = _parse_image(
        image,
        default_registry_host=config.docker_registry_host,
        official_registry_host=config.docker_registry_host,
    )
    if registry == config.docker_registry_host:
        token_url = (
            f"{config.docker_registry_auth_url}?"
            + urllib.parse.urlencode(
                {"service": config.docker_registry_service, "scope": f"repository:{repository}:pull"}
            )
        )
        manifest_url = f"{config.docker_registry_manifest_base_url.rstrip('/')}/{repository}/manifests/{tag}"
    elif registry == config.ghcr_registry_host:
        token_url = (
            f"{config.ghcr_registry_auth_url}?"
            + urllib.parse.urlencode(
                {"service": config.ghcr_registry_service, "scope": f"repository:{repository}:pull"}
            )
        )
        manifest_url = f"{config.ghcr_registry_manifest_base_url.rstrip('/')}/{repository}/manifests/{tag}"
    else:
        raise ReleaseVerificationError(f"Unsupported registry for public manifest check: {registry}")

    token_payload = _expect_dict(_fetch_json(token_url), f"{registry} token")
    token = token_payload.get("token")
    if not isinstance(token, str) or not token:
        raise ReleaseVerificationError(f"{registry} did not issue an anonymous pull token: {image}")

    request = urllib.request.Request(
        manifest_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": (
                "application/vnd.docker.distribution.manifest.list.v2+json,"
                "application/vnd.oci.image.index.v1+json,"
                "application/vnd.docker.distribution.manifest.v2+json"
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ReleaseVerificationError(f"Public manifest check failed for {image}")


def _verify_docker_registry(
    config: ReleaseVerificationConfig,
    manifest_exists: ManifestChecker,
) -> None:
    for tag in (config.version, config.minor_version):
        image = (
            f"{config.docker_registry_host}/"
            f"{config.docker_namespace}/{config.docker_image_name}:{tag}"
        )
        try:
            manifest_exists(image, config)
        except Exception as exc:
            raise ReleaseVerificationError(f"Docker registry manifest is not public: {image}") from exc


def _verify_ghcr(config: ReleaseVerificationConfig, manifest_exists: ManifestChecker) -> None:
    for tag in (config.version, config.minor_version):
        image = (
            f"{config.ghcr_registry_host}/"
            f"{config.docker_namespace}/{config.docker_image_name}:{tag}"
        )
        try:
            manifest_exists(image, config)
        except Exception as exc:
            raise ReleaseVerificationError(f"GHCR manifest is not public: {image}") from exc


def _verify_mcp_registry(config: ReleaseVerificationConfig, fetch_json: JsonFetcher) -> None:
    try:
        payload = _expect_dict(fetch_json(config.mcp_registry_search_url), "MCP Registry")
    except Exception as exc:
        raise ReleaseVerificationError(f"MCP Registry entry is not public: {config.version}") from exc
    encoded = json.dumps(payload, sort_keys=True)
    if config.mcp_registry_name not in encoded or config.version not in encoded:
        raise ReleaseVerificationError(f"MCP Registry version mismatch: expected {config.version}")


def _verify_homebrew(config: ReleaseVerificationConfig, fetch_text: TextFetcher) -> None:
    try:
        formula = fetch_text(config.homebrew_formula_url)
    except Exception as exc:
        raise ReleaseVerificationError("Homebrew formula is not public") from exc
    expected = f"mcp_broker-{config.version}.tar.gz"
    if expected not in formula:
        raise ReleaseVerificationError(f"Homebrew formula version mismatch: expected {config.version}")


def verify_public_release(
    config: ReleaseVerificationConfig,
    *,
    fetch_json: JsonFetcher = _fetch_json,
    fetch_text: TextFetcher = _fetch_text,
    manifest_exists: ManifestChecker = _verify_manifest_public,
    checks: Iterable[str] | None = None,
) -> list[str]:
    selected = set(checks or CHECK_ORDER)
    unknown = selected.difference(CHECK_ORDER)
    if unknown:
        raise ReleaseVerificationError(f"Unknown release verification checks: {sorted(unknown)}")

    failures: list[str] = []
    verified: list[str] = []
    for check in CHECK_ORDER:
        if check not in selected:
            continue
        try:
            if check == "github-release":
                _verify_github_release(config, fetch_json)
            elif check == "pypi":
                _verify_pypi(config, fetch_json)
            elif check == "npm":
                _verify_npm(config, fetch_json)
            elif check == "docker-hub":
                _verify_docker_hub(config, fetch_json)
            elif check == "docker-registry":
                _verify_docker_registry(config, manifest_exists)
            elif check == "ghcr":
                _verify_ghcr(config, manifest_exists)
            elif check == "mcp-registry":
                _verify_mcp_registry(config, fetch_json)
            elif check == "homebrew":
                _verify_homebrew(config, fetch_text)
        except ReleaseVerificationError as exc:
            failures.append(str(exc))
        else:
            LOGGER.info("public_release_verified surface=%s version=%s", check, config.version)
            verified.append(check)

    if failures:
        raise ReleaseVerificationError("; ".join(failures))
    return verified


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify public registry surfaces expose the intended mcp-broker release."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--checks", default=",".join(CHECK_ORDER))
    parser.add_argument("--npm-package", required=True)
    parser.add_argument("--docker-namespace", required=True)
    parser.add_argument("--docker-image-name", required=True)
    parser.add_argument("--mcp-registry-name", required=True)
    parser.add_argument("--github-release-url", required=True)
    parser.add_argument("--pypi-version-url", required=True)
    parser.add_argument("--npm-registry-url", required=True)
    parser.add_argument("--docker-hub-api-repository-base-url", required=True)
    parser.add_argument("--docker-registry-service", required=True)
    parser.add_argument("--docker-registry-host", required=True)
    parser.add_argument("--docker-registry-auth-url", required=True)
    parser.add_argument("--docker-registry-manifest-base-url", required=True)
    parser.add_argument("--ghcr-registry-service", required=True)
    parser.add_argument("--ghcr-registry-host", required=True)
    parser.add_argument("--ghcr-registry-auth-url", required=True)
    parser.add_argument("--ghcr-registry-manifest-base-url", required=True)
    parser.add_argument("--mcp-registry-search-url", required=True)
    parser.add_argument(
        "--homebrew-formula-url",
        required=True,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    checks = {check.strip() for check in args.checks.split(",") if check.strip()}
    config = ReleaseVerificationConfig(
        version=args.version,
        npm_package=args.npm_package,
        docker_namespace=args.docker_namespace,
        docker_image_name=args.docker_image_name,
        mcp_registry_name=args.mcp_registry_name,
        github_release_url=args.github_release_url,
        pypi_version_url=args.pypi_version_url,
        npm_registry_url=args.npm_registry_url,
        docker_hub_api_repository_base_url=args.docker_hub_api_repository_base_url,
        docker_registry_service=args.docker_registry_service,
        docker_registry_host=args.docker_registry_host,
        docker_registry_auth_url=args.docker_registry_auth_url,
        docker_registry_manifest_base_url=args.docker_registry_manifest_base_url,
        ghcr_registry_service=args.ghcr_registry_service,
        ghcr_registry_host=args.ghcr_registry_host,
        ghcr_registry_auth_url=args.ghcr_registry_auth_url,
        ghcr_registry_manifest_base_url=args.ghcr_registry_manifest_base_url,
        mcp_registry_search_url=args.mcp_registry_search_url,
        homebrew_formula_url=args.homebrew_formula_url,
    )
    try:
        verify_public_release(config, checks=checks)
    except ReleaseVerificationError as exc:
        LOGGER.error("public_release_verification_failed version=%s error=%s", args.version, exc)
        return 1
    LOGGER.info("public_release_verification_passed version=%s", args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
