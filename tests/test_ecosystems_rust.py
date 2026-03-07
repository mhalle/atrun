"""Tests for atrun.ecosystems.rust — lockfile parsing, URL building, install args."""

from __future__ import annotations

import pytest

from atrun.ecosystems.rust import (
    _crate_download_url,
    generate_install_args,
    generate_run_args,
    parse_lockfile,
)


def test_crate_download_url():
    assert _crate_download_url("ripgrep", "14.1.0") == (
        "https://crates.io/api/v1/crates/ripgrep/14.1.0/download"
    )


def test_parse_lockfile_basic(cargo_lock_content):
    entries = parse_lockfile(cargo_lock_content)
    assert len(entries) == 2
    names = [e["name"] for e in entries]
    assert "ripgrep" in names
    assert "aho-corasick" in names


def test_parse_lockfile_hash_prefix(cargo_lock_content):
    entries = parse_lockfile(cargo_lock_content)
    for e in entries:
        assert e["hash"].startswith("sha256:")


def test_parse_lockfile_skips_non_crates_io():
    content = '''\
[[package]]
name = "mylocal"
version = "0.1.0"
source = "path+file:///home/user/mylocal"
'''
    entries = parse_lockfile(content)
    assert len(entries) == 0


def test_parse_lockfile_resolves_deps(cargo_lock_content):
    entries = parse_lockfile(cargo_lock_content)
    ripgrep = next(e for e in entries if e["name"] == "ripgrep")
    assert "dependencies" in ripgrep
    assert any("aho-corasick@" in d for d in ripgrep["dependencies"])


def test_parse_lockfile_deduplicates():
    content = '''\
[[package]]
name = "serde"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaa"

[[package]]
name = "serde"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaa"
'''
    entries = parse_lockfile(content)
    assert len(entries) == 1


def test_generate_install_args():
    record = {
        "package": "ripgrep",
        "resolved": [{"name": "ripgrep", "version": "14.1.0"}],
    }
    args = generate_install_args(record)
    assert args == ["cargo", "install", "ripgrep@14.1.0"]


def test_generate_run_args():
    record = {"package": "ripgrep"}
    args = generate_run_args(record)
    assert args == ["cargo", "install", "--locked", "ripgrep"]


def test_generate_install_args_missing():
    record = {"package": "missing", "resolved": [{"name": "other", "version": "1.0"}]}
    with pytest.raises(SystemExit, match="not found"):
        generate_install_args(record)
