"""Tests for atrun.run — TID decoding, regexes, fetch_record, generate_requirements."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from atrun.run import (
    AT_URI_RE,
    BSKY_POST_RE,
    SHORTHAND_RE,
    _decode_tid_timestamp,
    fetch_record,
    generate_requirements,
)


# --- Pure function tests ---


def test_decode_tid_valid():
    # Known TID: "3mgxyz" won't necessarily be valid; use a crafted one.
    # The TID "3jqfcqzm3fs2j" is a known-valid TID format.
    result = _decode_tid_timestamp("3jqfcqzm3fs2j")
    assert result is not None
    assert "T" in result  # ISO 8601 has a T separator


def test_decode_tid_invalid():
    assert _decode_tid_timestamp("!!!") is None


def test_at_uri_re_valid():
    m = AT_URI_RE.match("at://did:plc:abc123/dev.atpub.manifest/3mgxyz")
    assert m is not None
    assert m.group(1) == "did:plc:abc123"
    assert m.group(2) == "dev.atpub.manifest"
    assert m.group(3) == "3mgxyz"


def test_at_uri_re_invalid():
    assert AT_URI_RE.match("https://example.com") is None


def test_bsky_post_re_valid():
    m = BSKY_POST_RE.match("https://bsky.app/profile/alice.bsky.social/post/3mgxyz")
    assert m is not None
    assert m.group(1) == "alice.bsky.social"
    assert m.group(2) == "3mgxyz"


def test_shorthand_re_with_version():
    m = SHORTHAND_RE.match("@alice.bsky.social:cowsay@1.6.0")
    assert m is not None
    assert m.group(1) == "alice.bsky.social"
    assert m.group(2) == "cowsay"
    assert m.group(3) == "1.6.0"


def test_shorthand_re_without_version():
    m = SHORTHAND_RE.match("@alice.bsky.social:cowsay")
    assert m is not None
    assert m.group(1) == "alice.bsky.social"
    assert m.group(2) == "cowsay"
    assert m.group(3) is None


def test_generate_requirements_with_record(sample_manifest_record):
    resolved = sample_manifest_record["resolved"]
    result = generate_requirements(resolved, record=sample_manifest_record)
    assert "cowsay@1.6.0" in result
    assert "string-width@4.2.3" in result


# --- Mocked HTTP tests ---


@patch("atrun.run.httpx.get")
@patch("atrun.run._resolve_handle", return_value="alice.bsky.social")
def test_fetch_record_at_uri(mock_handle, mock_get):
    from tests.conftest import mock_response
    mock_get.return_value = mock_response(json_data={
        "uri": "at://did:plc:abc/dev.atpub.manifest/3mgxyz",
        "cid": "bafyreicid",
        "value": {"$type": "dev.atpub.manifest", "package": "test"},
    })

    result = fetch_record("at://did:plc:abc/dev.atpub.manifest/3mgxyz")
    assert result["at"]["uri"] == "at://did:plc:abc/dev.atpub.manifest/3mgxyz"
    assert result["content"]["package"] == "test"


@patch("atrun.run.httpx.get")
def test_fetch_record_xrpc_url(mock_get):
    from tests.conftest import mock_response
    mock_get.return_value = mock_response(json_data={
        "uri": "at://did:plc:abc/dev.atpub.manifest/3mgxyz",
        "cid": "bafyreicid",
        "value": {"$type": "dev.atpub.manifest", "package": "test"},
    })

    result = fetch_record("https://bsky.social/xrpc/com.atproto.repo.getRecord?repo=did:plc:abc&collection=dev.atpub.manifest&rkey=3mgxyz")
    assert result["at"]["cid"] == "bafyreicid"
    assert result["content"]["package"] == "test"


def test_fetch_record_garbage():
    with pytest.raises(SystemExit, match="Invalid AT URI"):
        fetch_record("garbage-string")
