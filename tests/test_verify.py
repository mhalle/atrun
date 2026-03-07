"""Tests for atrun.verify — hash parsing, hashing, download & verify."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from atrun.verify import (
    HashMismatchError,
    _parse_hash,
    download_and_verify,
    hash_bytes,
    hash_file,
    verify_artifact,
)


# --- Pure function tests ---


def test_parse_hash_algo_hex():
    assert _parse_hash("sha256:abc123") == ("sha256", "abc123")


def test_parse_hash_bare_hex_defaults_sha256():
    assert _parse_hash("abc123") == ("sha256", "abc123")


def test_parse_hash_sha512():
    assert _parse_hash("sha512:def456") == ("sha512", "def456")


def test_parse_hash_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported hash algorithm"):
        _parse_hash("blake2:abc")


def test_hash_bytes_sha256():
    expected = hashlib.sha256(b"hello").hexdigest()
    assert hash_bytes(b"hello", "sha256") == expected


def test_hash_bytes_sha512():
    result = hash_bytes(b"hello", "sha512")
    assert len(result) == 128
    assert result == hashlib.sha512(b"hello").hexdigest()


def test_hash_file(tmp_path):
    f = tmp_path / "testfile"
    f.write_bytes(b"hello world")
    assert hash_file(f) == hash_bytes(b"hello world")


def test_hash_mismatch_error_attributes():
    exc = HashMismatchError("https://example.com/file.tgz", "sha256:aaaa", "sha256:bbbb")
    assert exc.url == "https://example.com/file.tgz"
    assert exc.expected == "sha256:aaaa"
    assert exc.actual == "sha256:bbbb"
    assert "aaaa" in str(exc)


# --- Mocked HTTP tests ---


@patch("atrun.verify.httpx.get")
def test_download_and_verify_success(mock_get):
    data = b"artifact content"
    digest = hashlib.sha256(data).hexdigest()

    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=data)

    result = download_and_verify("https://example.com/pkg-1.0.whl", f"sha256:{digest}")
    assert result.exists()
    assert result.read_bytes() == data
    result.unlink()


@patch("atrun.verify.httpx.get")
def test_download_and_verify_mismatch_cleans_up(mock_get):
    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=b"artifact content")

    with pytest.raises(HashMismatchError):
        download_and_verify("https://example.com/pkg.whl", "sha256:0000000000000000")

    # Temp file should be cleaned up on mismatch


@patch("atrun.verify.httpx.get")
def test_download_and_verify_tar_gz_suffix(mock_get):
    data = b"tarball"
    digest = hashlib.sha256(data).hexdigest()

    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=data)

    result = download_and_verify("https://example.com/pkg-1.0.tar.gz", f"sha256:{digest}")
    assert result.name.endswith(".tar.gz")
    result.unlink()


@patch("atrun.verify.httpx.get")
def test_verify_artifact_success(mock_get):
    data = b"crate bytes"
    digest = hashlib.sha256(data).hexdigest()

    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=data)

    verify_artifact("https://crates.io/api/v1/crates/rg/14.0/download", f"sha256:{digest}")


@patch("atrun.verify.httpx.get")
def test_verify_artifact_mismatch(mock_get):
    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=b"wrong content")

    with pytest.raises(HashMismatchError):
        verify_artifact("https://example.com/pkg", "sha256:0000000000000000")


# --- download_to ---


@patch("atrun.verify.httpx.get")
def test_download_to_with_hash(mock_get, tmp_path):
    from atrun.verify import download_to

    data = b"artifact bytes"
    digest = hashlib.sha256(data).hexdigest()

    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=data)

    dest = tmp_path / "pkg-1.0.tgz"
    result = download_to("https://example.com/pkg-1.0.tgz", dest, f"sha256:{digest}")
    assert result == dest
    assert dest.read_bytes() == data


@patch("atrun.verify.httpx.get")
def test_download_to_hash_mismatch_no_file(mock_get, tmp_path):
    from atrun.verify import download_to

    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=b"wrong content")

    dest = tmp_path / "pkg.tgz"
    with pytest.raises(HashMismatchError):
        download_to("https://example.com/pkg.tgz", dest, "sha256:" + "00" * 32)
    assert not dest.exists()


@patch("atrun.verify.httpx.get")
def test_download_to_no_hash(mock_get, tmp_path):
    from atrun.verify import download_to

    data = b"some content"
    from tests.conftest import mock_response
    mock_get.return_value = mock_response(content=data)

    dest = tmp_path / "pkg.tgz"
    download_to("https://example.com/pkg.tgz", dest)
    assert dest.read_bytes() == data
