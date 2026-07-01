from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
import zipfile

import pytest


pytestmark = pytest.mark.unit


def test_runtime_artifact_verifier_accepts_safe_zip_with_matching_digest(
    tmp_path: Path,
) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {"bin/mcp-broker": "#!/bin/sh\n"})
    digest = _sha256(artifact_path)

    report = RuntimeArtifactVerifier().verify(
        artifact_path=artifact_path,
        expected_digest=f"sha256:{digest}",
    )

    assert report == {
        "artifact_path": str(artifact_path),
        "archive_format": "zip",
        "digest_algorithm": "sha256",
        "digest_verified": True,
        "members_checked": 1,
        "safe_to_activate": True,
    }


def test_runtime_artifact_verifier_rejects_digest_mismatch(tmp_path: Path) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {"bin/mcp-broker": "#!/bin/sh\n"})

    with pytest.raises(RuntimeArtifactError, match="digest mismatch"):
        RuntimeArtifactVerifier().verify(
            artifact_path=artifact_path,
            expected_digest=f"sha256:{'0' * 64}",
        )


def test_runtime_artifact_verifier_rejects_zip_path_traversal(tmp_path: Path) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {"../escape": "bad"})

    with pytest.raises(RuntimeArtifactError, match="unsafe archive member"):
        RuntimeArtifactVerifier().verify(
            artifact_path=artifact_path,
            expected_digest=f"sha256:{_sha256(artifact_path)}",
        )


@pytest.mark.parametrize("member_name", ["bin/../escape", "..\\escape", "C:\\escape"])
def test_runtime_artifact_verifier_rejects_cross_platform_traversal(
    tmp_path: Path,
    member_name: str,
) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {member_name: "bad"})

    with pytest.raises(RuntimeArtifactError, match="unsafe archive member"):
        RuntimeArtifactVerifier().verify(
            artifact_path=artifact_path,
            expected_digest=f"sha256:{_sha256(artifact_path)}",
        )


def test_runtime_artifact_verifier_rejects_tar_absolute_member(tmp_path: Path) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.tar"
    _write_tar(artifact_path, {"/tmp/escape": "bad"})

    with pytest.raises(RuntimeArtifactError, match="unsafe archive member"):
        RuntimeArtifactVerifier().verify(
            artifact_path=artifact_path,
            expected_digest=f"sha256:{_sha256(artifact_path)}",
        )


def test_runtime_artifact_verifier_rejects_tar_special_file(tmp_path: Path) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.tar"
    _write_tar_special_file(artifact_path, "bin/runtime.pipe")

    with pytest.raises(RuntimeArtifactError, match="unsafe archive member"):
        RuntimeArtifactVerifier().verify(
            artifact_path=artifact_path,
            expected_digest=f"sha256:{_sha256(artifact_path)}",
        )


def test_runtime_artifact_verifier_rejects_empty_archive(tmp_path: Path) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {})

    with pytest.raises(RuntimeArtifactError, match="empty runtime artifact"):
        RuntimeArtifactVerifier().verify(
            artifact_path=artifact_path,
            expected_digest=f"sha256:{_sha256(artifact_path)}",
        )


def test_runtime_artifact_verifier_rejects_unsupported_archive(tmp_path: Path) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.bin"
    artifact_path.write_bytes(b"not an archive")

    with pytest.raises(RuntimeArtifactError, match="unsupported runtime artifact"):
        RuntimeArtifactVerifier().verify(
            artifact_path=artifact_path,
            expected_digest=f"sha256:{_sha256(artifact_path)}",
        )


def test_runtime_artifact_verify_cli_reports_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker.cli import main

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {"bin/mcp-broker": "#!/bin/sh\n"})
    digest = _sha256(artifact_path)

    assert (
        main(
            [
                "runtime",
                "artifact-verify",
                "--artifact",
                str(artifact_path),
                "--digest",
                f"sha256:{digest}",
            ]
        )
        == 0
    )

    assert '"safe_to_activate": true' in capsys.readouterr().out


def test_runtime_artifact_verify_cli_rejects_digest_mismatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.cli import main

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {"bin/mcp-broker": "#!/bin/sh\n"})

    assert (
        main(
            [
                "runtime",
                "artifact-verify",
                "--artifact",
                str(artifact_path),
                "--digest",
                f"sha256:{'0' * 64}",
            ]
        )
        == 1
    )

    assert "digest mismatch" in capsys.readouterr().err


def test_runtime_artifact_verify_cli_accepts_metadata_sidecar(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.cli import main

    metadata_path = _write_metadata_sidecar(tmp_path, entrypoint="bin/mcp-broker")

    assert (
        main(
            [
                "runtime",
                "artifact-verify",
                "--metadata",
                str(metadata_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert '"entrypoint": "bin/mcp-broker"' in output
    assert '"safe_to_activate": true' in output


def test_runtime_artifact_verifier_accepts_metadata_sidecar(tmp_path: Path) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactVerifier

    metadata_path = _write_metadata_sidecar(tmp_path, entrypoint="bin/mcp-broker")
    artifact_path = tmp_path / "runtime.zip"

    report = RuntimeArtifactVerifier().verify_metadata_file(metadata_path)

    assert report["artifact_path"] == str(artifact_path)
    assert report["entrypoint"] == "bin/mcp-broker"
    assert report["version"] == "2.1.0"
    assert report["safe_to_activate"] is True


def test_runtime_artifact_verifier_rejects_metadata_artifact_path_escape(
    tmp_path: Path,
) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    artifact_path = tmp_path / "runtime.zip"
    _write_zip(artifact_path, {"bin/mcp-broker": "#!/bin/sh\n"})
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    metadata_path = metadata_dir / "runtime-metadata.json"
    metadata_path.write_text(
        (
            "{"
            f'"artifact_digest": "sha256:{_sha256(artifact_path)}", '
            '"artifact_path": "../runtime.zip", '
            '"entrypoint": "bin/mcp-broker", '
            '"version": "2.1.0"'
            "}"
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeArtifactError, match="artifact path"):
        RuntimeArtifactVerifier().verify_metadata_file(metadata_path)


@pytest.mark.parametrize("entrypoint", ["../escape", "bin/../escape", "..\\escape", "C:\\escape"])
def test_runtime_artifact_verifier_rejects_unsafe_metadata_entrypoint(
    tmp_path: Path,
    entrypoint: str,
) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    metadata_path = _write_metadata_sidecar(tmp_path, entrypoint=entrypoint)

    with pytest.raises(RuntimeArtifactError, match="entrypoint"):
        RuntimeArtifactVerifier().verify_metadata_file(metadata_path)


def test_runtime_artifact_verifier_rejects_missing_metadata_entrypoint(
    tmp_path: Path,
) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    metadata_path = _write_metadata_sidecar(tmp_path, entrypoint="bin/missing")

    with pytest.raises(RuntimeArtifactError, match="entrypoint"):
        RuntimeArtifactVerifier().verify_metadata_file(metadata_path)


def test_runtime_artifact_verifier_rejects_non_executable_metadata_entrypoint(
    tmp_path: Path,
) -> None:
    from mcp_broker.runtime_artifact import RuntimeArtifactError, RuntimeArtifactVerifier

    metadata_path = _write_metadata_sidecar(
        tmp_path,
        entrypoint="bin/mcp-broker",
        executable=False,
    )

    with pytest.raises(RuntimeArtifactError, match="entrypoint"):
        RuntimeArtifactVerifier().verify_metadata_file(metadata_path)


def _write_zip(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for member_name, content in members.items():
            info = zipfile.ZipInfo(member_name)
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            archive.writestr(info, content)


def _write_tar(path: Path, members: dict[str, str]) -> None:
    with tarfile.open(path, "w") as archive:
        for member_name, content in members.items():
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _write_tar_special_file(path: Path, member_name: str) -> None:
    with tarfile.open(path, "w") as archive:
        info = tarfile.TarInfo(member_name)
        info.type = tarfile.FIFOTYPE
        archive.addfile(info)


def _write_metadata_sidecar(
    tmp_path: Path,
    *,
    entrypoint: str,
    executable: bool = True,
) -> Path:
    artifact_path = tmp_path / "runtime.zip"
    with zipfile.ZipFile(artifact_path, "w") as archive:
        info = zipfile.ZipInfo("bin/mcp-broker")
        file_mode = 0o755 if executable else 0o644
        info.external_attr = (stat.S_IFREG | file_mode) << 16
        archive.writestr(info, "#!/bin/sh\n")
    metadata_path = tmp_path / "runtime-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "artifact_digest": f"sha256:{_sha256(artifact_path)}",
                "artifact_path": "runtime.zip",
                "entrypoint": entrypoint,
                "version": "2.1.0",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return metadata_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
