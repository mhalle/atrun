"""Tests for atrun.ecosystems.go — lockfile parsing, hash conversion, install args."""

from __future__ import annotations

import base64
import hashlib

import pytest

from atrun.ecosystems.go import (
    _convert_h1_hash,
    _module_download_url,
    generate_install_args,
    generate_run_args,
    parse_lockfile,
)


def test_module_download_url():
    assert _module_download_url("golang.org/x/text", "v0.14.0") == (
        "https://proxy.golang.org/golang.org/x/text/@v/v0.14.0.zip"
    )


def test_module_download_url_uppercase_escape():
    url = _module_download_url("github.com/Azure/azure-sdk", "v1.0.0")
    assert "!azure" in url
    assert "Azure" not in url


def test_convert_h1_hash():
    raw = hashlib.sha256(b"module content").digest()
    b64 = base64.b64encode(raw).decode()
    result = _convert_h1_hash(f"h1:{b64}")
    assert result == f"sha256:{raw.hex()}"


def test_convert_h1_hash_passthrough():
    assert _convert_h1_hash("sha256:abc123") == "sha256:abc123"


def test_parse_lockfile_basic(go_sum_content):
    entries = parse_lockfile(go_sum_content)
    assert len(entries) == 2
    names = [e["name"] for e in entries]
    assert "golang.org/x/text" in names
    assert "golang.org/x/net" in names


def test_parse_lockfile_sorted(go_sum_content):
    entries = parse_lockfile(go_sum_content)
    names = [e["name"] for e in entries]
    assert names == sorted(names)


def test_parse_lockfile_skips_go_mod(go_sum_content):
    entries = parse_lockfile(go_sum_content)
    # go.mod lines should be skipped; we have 2 module entries
    for e in entries:
        assert "/go.mod" not in e["version"]


def test_parse_lockfile_deduplicates():
    content = """\
golang.org/x/text v0.14.0 h1:abc=
golang.org/x/text v0.14.0 h1:abc=
"""
    entries = parse_lockfile(content)
    assert len(entries) == 1


def test_parse_lockfile_empty():
    assert parse_lockfile("") == []


def test_generate_install_args():
    record = {
        "package": "golang.org/x/text",
        "resolved": [{"name": "golang.org/x/text", "version": "v0.14.0"}],
    }
    args = generate_install_args(record)
    assert args == ["go", "install", "golang.org/x/text@v0.14.0"]


def test_generate_run_args():
    record = {
        "package": "golang.org/x/text",
        "resolved": [{"name": "golang.org/x/text", "version": "v0.14.0"}],
    }
    args = generate_run_args(record)
    assert args == ["go", "run", "golang.org/x/text@v0.14.0"]


def test_generate_install_args_missing():
    record = {"package": "missing", "resolved": [{"name": "other", "version": "v1.0"}]}
    with pytest.raises(SystemExit, match="not found"):
        generate_install_args(record)
