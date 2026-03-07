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
    assert all("hash" in e for e in entries)
    assert all("url" in e for e in entries)


def test_parse_lockfile_sorted(pylock_toml_content):
    entries = parse_lockfile(pylock_toml_content)
    names = [e["name"] for e in entries]
    assert names == sorted(names)


def test_parse_lockfile_sha512(pylock_toml_sha512):
    entries = parse_lockfile(pylock_toml_sha512)
    assert len(entries) == 1
    assert entries[0]["hash"].startswith("sha512:")


def test_parse_lockfile_sdist_fallback(pylock_toml_sdist):
    entries = parse_lockfile(pylock_toml_sdist)
    assert len(entries) == 1
    assert entries[0]["name"] == "bar"
    assert entries[0]["url"].endswith(".tar.gz")


def test_extract_hash_sha256():
    assert _extract_hash({"sha256": "abc"}) == "sha256:abc"


def test_extract_hash_empty():
    assert _extract_hash({}) is None


def test_generate_requirements():
    resolved = [
        {"name": "click", "url": "https://example.com/click.whl", "hash": "sha256:abc"},
    ]
    result = generate_requirements(resolved)
    assert "click @ https://example.com/click.whl --hash=sha256:abc" in result


def test_generate_install_args():
    record = {
        "package": "atrun",
        "resolved": [{"name": "atrun", "version": "0.5.0", "url": "https://example.com/atrun.whl"}],
    }
    args = generate_install_args(record)
    assert args[0] == "uv"
    assert "tool" in args
    assert "install" in args


def test_generate_install_args_missing_package():
    record = {"package": "missing", "resolved": [{"name": "other", "version": "1.0"}]}
    with pytest.raises(SystemExit, match="not found"):
        generate_install_args(record)


def test_build_metadata():
    meta = build_metadata()
    assert "pythonVersion" in meta
