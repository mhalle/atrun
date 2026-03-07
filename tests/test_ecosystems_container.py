"""Tests for atrun.ecosystems.container — Docker/OCI container support."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from atrun.ecosystems.container import (
    _build_image_ref,
    _build_oci_url,
    _parse_image_ref,
    _resolve_digest,
    format_resolve_output,
    generate_install_args,
    generate_run_args,
    parse_lockfile,
    verify_digest,
)


# --- _parse_image_ref ---


def test_parse_bare_name():
    result = _parse_image_ref("nginx")
    assert result["name"] == "docker.io/library/nginx"
    assert result["tag"] == "latest"
    assert result["registry"] == "docker.io"


def test_parse_bare_name_with_tag():
    result = _parse_image_ref("nginx:1.25")
    assert result["name"] == "docker.io/library/nginx"
    assert result["tag"] == "1.25"


def test_parse_user_name():
    result = _parse_image_ref("user/app")
    assert result["name"] == "docker.io/user/app"
    assert result["tag"] == "latest"


def test_parse_user_name_with_tag():
    result = _parse_image_ref("user/app:v2")
    assert result["name"] == "docker.io/user/app"
    assert result["tag"] == "v2"


def test_parse_full_registry():
    result = _parse_image_ref("ghcr.io/user/app:v2")
    assert result["name"] == "ghcr.io/user/app"
    assert result["tag"] == "v2"
    assert result["registry"] == "ghcr.io"


def test_parse_digest_ref():
    result = _parse_image_ref("ghcr.io/user/app@sha256:abc123")
    assert result["name"] == "ghcr.io/user/app"
    assert result["digest"] == "sha256:abc123"
    assert result["tag"] is None


# --- _build_image_ref ---


def test_build_image_ref_with_hash():
    entry = {"name": "ghcr.io/user/app", "version": "1.0.0", "digest": "sha256:abc123"}
    assert _build_image_ref(entry) == "ghcr.io/user/app@sha256:abc123"


def test_build_image_ref_without_hash():
    entry = {"name": "ghcr.io/user/app", "version": "1.0.0", "digest": ""}
    assert _build_image_ref(entry) == "ghcr.io/user/app:1.0.0"


# --- _build_oci_url ---


def test_build_oci_url():
    assert _build_oci_url("ghcr.io/user/app", "1.0.0") == "oci://ghcr.io/user/app:1.0.0"


def test_build_oci_url_bare():
    assert _build_oci_url("docker.io/library/nginx", "1.25") == "oci://docker.io/library/nginx:1.25"


# --- _resolve_digest ---


def test_resolve_digest_docker():
    mock_result = MagicMock()
    mock_result.stdout = '{"Descriptor": {"digest": "sha256:abc123"}}'
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = _resolve_digest("nginx:1.25", "docker")
        assert result == "sha256:abc123"
        mock_run.assert_called_once()


def test_resolve_digest_crane():
    mock_result = MagicMock()
    mock_result.stdout = "sha256:abc123\n"
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = _resolve_digest("nginx:1.25", "crane")
        assert result == "sha256:abc123"
        mock_run.assert_called_once_with(
            ["crane", "digest", "nginx:1.25"],
            capture_output=True, text=True, check=True,
        )


def test_resolve_digest_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(SystemExit, match="not found"):
            _resolve_digest("nginx:1.25", "docker")


# --- parse_lockfile ---


def test_parse_lockfile_compose_yaml():
    content = """\
services:
  web:
    image: ghcr.io/user/app:1.0.0
  db:
    image: postgres:16
"""
    with patch("atrun.ecosystems.container._resolve_digest", return_value="sha256:abc"):
        entries = parse_lockfile(content)
    assert len(entries) == 2
    # Sorted by name
    assert entries[0]["name"] == "docker.io/library/postgres"
    assert entries[0]["version"] == "16"
    assert entries[1]["name"] == "ghcr.io/user/app"
    assert entries[1]["version"] == "1.0.0"


def test_parse_lockfile_images_text():
    content = """\
# My images
ghcr.io/user/api:2.0.0
nginx:1.25
"""
    with patch("atrun.ecosystems.container._resolve_digest", return_value="sha256:def"):
        entries = parse_lockfile(content)
    assert len(entries) == 2
    assert entries[0]["name"] == "docker.io/library/nginx"
    assert entries[1]["name"] == "ghcr.io/user/api"


def test_parse_lockfile_artifact_type():
    content = """\
services:
  web:
    image: ghcr.io/user/app:1.0.0
"""
    with patch("atrun.ecosystems.container._resolve_digest", return_value="sha256:abc"):
        entries = parse_lockfile(content)
    assert entries[0]["artifactType"] == "image"


def test_parse_lockfile_compose_platform_metadata():
    content = """\
services:
  web:
    image: ghcr.io/user/app:1.0.0
    platform: linux/amd64
  db:
    image: postgres:16
"""
    with patch("atrun.ecosystems.container._resolve_digest", return_value="sha256:abc"):
        entries = parse_lockfile(content)
    web = next(e for e in entries if e["name"] == "ghcr.io/user/app")
    db = next(e for e in entries if e["name"] == "docker.io/library/postgres")
    assert web["metadata"] == {"platform": "linux/amd64"}
    assert "metadata" not in db


# --- generate_install_args ---


def test_generate_install_args():
    record = {
        "package": "ghcr.io/user/app",
        "artifacts": [
            {"name": "ghcr.io/user/app", "version": "1.0.0", "digest": "sha256:abc123"},
        ],
    }
    args = generate_install_args(record)
    assert args == ["docker", "pull", "ghcr.io/user/app@sha256:abc123"]


def test_generate_install_args_crane():
    record = {
        "package": "ghcr.io/user/app",
        "artifacts": [
            {"name": "ghcr.io/user/app", "version": "1.0.0", "digest": "sha256:abc123"},
        ],
    }
    args = generate_install_args(record, engine="crane")
    assert args == ["crane", "pull", "ghcr.io/user/app@sha256:abc123"]


# --- generate_run_args ---


def test_generate_run_args():
    record = {
        "package": "ghcr.io/user/app",
        "artifacts": [
            {"name": "ghcr.io/user/app", "version": "1.0.0", "digest": "sha256:abc123"},
        ],
    }
    args = generate_run_args(record)
    assert args == ["docker", "run", "--rm", "ghcr.io/user/app@sha256:abc123"]


# --- verify_digest ---


def test_verify_digest_match():
    with patch("atrun.ecosystems.container._resolve_digest", return_value="sha256:abc123"):
        assert verify_digest("nginx:1.25", "sha256:abc123") is True


def test_verify_digest_mismatch():
    with patch("atrun.ecosystems.container._resolve_digest", return_value="sha256:different"):
        with pytest.raises(SystemExit, match="Digest mismatch"):
            verify_digest("nginx:1.25", "sha256:abc123")


# --- format_resolve_output ---


def test_format_resolve_output():
    resolved = [
        {"name": "ghcr.io/user/app", "version": "1.0.0"},
        {"name": "docker.io/library/postgres", "version": "16"},
    ]
    output = format_resolve_output(resolved)
    assert "ghcr.io/user/app:1.0.0" in output
    assert "docker.io/library/postgres:16" in output
