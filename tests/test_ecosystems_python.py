"""Tests for atrun.ecosystems.python — lockfile parsing and install args."""

from __future__ import annotations

import pytest

from atrun.ecosystems.python import (
    _extract_hash,
    build_metadata,
    generate_install_args,
    generate_requirements,
    parse_lockfile,
)


def test_parse_lockfile_basic(pylock_toml_content):
    entries = parse_lockfile(pylock_toml_content)
    assert len(entries) == 2
    names = [e["name"] for e in entries]
    assert "click" in names
    assert "httpx" in names
    assert all("digest" in e for e in entries)
    assert all("url" in e for e in entries)


def test_parse_lockfile_sorted(pylock_toml_content):
    entries = parse_lockfile(pylock_toml_content)
    names = [e["name"] for e in entries]
    assert names == sorted(names)


def test_parse_lockfile_sha512(pylock_toml_sha512):
    entries = parse_lockfile(pylock_toml_sha512)
    assert len(entries) == 1
    assert entries[0]["digest"].startswith("sha512:")


def test_parse_lockfile_sdist_fallback(pylock_toml_sdist):
    entries = parse_lockfile(pylock_toml_sdist)
    assert len(entries) == 1
    assert entries[0]["name"] == "bar"
    assert entries[0]["url"].endswith(".tar.gz")


def test_parse_lockfile_requires_python_metadata():
    content = '''\
lock-version = 1

[[packages]]
name = "click"
version = "8.1.7"
requires-python = ">=3.7"

[[packages.wheels]]
url = "https://files.pythonhosted.org/packages/click-8.1.7-py3-none-any.whl"

[packages.wheels.hashes]
sha256 = "ae74fb96c20a0277a1d615f1e4d73c8414f5a98db8b799a7931d1582f3390c28"
'''
    entries = parse_lockfile(content)
    assert len(entries) == 1
    assert entries[0]["metadata"] == {"requires-python": ">=3.7"}


def test_parse_lockfile_no_metadata_when_absent(pylock_toml_content):
    entries = parse_lockfile(pylock_toml_content)
    assert all("metadata" not in e for e in entries)


def test_parse_lockfile_artifact_type_wheel(pylock_toml_content):
    entries = parse_lockfile(pylock_toml_content)
    assert all(e["artifactType"] == "wheel" for e in entries)


def test_parse_lockfile_artifact_type_sdist(pylock_toml_sdist):
    entries = parse_lockfile(pylock_toml_sdist)
    assert entries[0]["artifactType"] == "sdist"


def test_extract_hash_sha256():
    assert _extract_hash({"sha256": "abc"}) == "sha256:abc"


def test_extract_hash_empty():
    assert _extract_hash({}) is None


def test_generate_requirements():
    resolved = [
        {"name": "click", "url": "https://example.com/click.whl", "digest": "sha256:abc"},
    ]
    result = generate_requirements(resolved)
    assert "click @ https://example.com/click.whl --hash=sha256:abc" in result


def test_generate_install_args():
    record = {
        "package": "atrun",
        "artifacts": [{"name": "atrun", "version": "0.5.0", "url": "https://example.com/atrun.whl"}],
    }
    args = generate_install_args(record)
    assert args[0] == "uv"
    assert "tool" in args
    assert "install" in args


def test_generate_install_args_missing_package():
    record = {"package": "missing", "artifacts": [{"name": "other", "version": "1.0"}]}
    with pytest.raises(SystemExit, match="not found"):
        generate_install_args(record)


def test_build_metadata():
    meta = build_metadata()
    assert "pythonVersion" in meta
