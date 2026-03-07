"""Tests for atrun.cli — CliRunner integration tests."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

from click.testing import CliRunner

from atrun.cli import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Social package distribution" in result.output


def _make_record(package, version, hash_str, url, extra_resolved=None):
    """Helper to build a fetch_record-style return value."""
    resolved = [{"name": package, "version": version, "hash": hash_str, "url": url}]
    if extra_resolved:
        resolved.extend(extra_resolved)
    return {
        "at": {
            "uri": f"at://did:plc:abc/dev.atpub.manifest/3mgxyz",
            "cid": "bafyreicid",
            "did": "did:plc:abc",
            "handle": "alice.bsky.social",
        },
        "content": {
            "$type": "dev.atpub.manifest",
            "package": package,
            "version": version,
            "resolved": resolved,
        },
    }


@patch("atrun.cli.fetch_record" if False else "atrun.run.fetch_record")
@patch("atrun.verify.httpx.get")
def test_verify_success(mock_verify_get, mock_fetch):
    from tests.conftest import mock_response

    data = b"artifact content"
    digest = hashlib.sha256(data).hexdigest()

    mock_fetch.return_value = _make_record("cowsay", "1.6.0", f"sha256:{digest}", "https://example.com/cowsay.tgz")
    mock_verify_get.return_value = mock_response(content=data)

    runner = CliRunner()
    result = runner.invoke(cli, ["verify", "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    assert "Verified" in result.output


@patch("atrun.run.fetch_record")
@patch("atrun.verify.httpx.get")
def test_verify_json(mock_verify_get, mock_fetch):
    from tests.conftest import mock_response

    data = b"artifact content"
    digest = hashlib.sha256(data).hexdigest()

    mock_fetch.return_value = _make_record("cowsay", "1.6.0", f"sha256:{digest}", "https://example.com/cowsay.tgz")
    mock_verify_get.return_value = mock_response(content=data)

    runner = CliRunner()
    result = runner.invoke(cli, ["verify", "--json", "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    # Output may include stderr "Verifying..." line; extract JSON portion
    json_start = result.output.index("{")
    output = json.loads(result.output[json_start:])
    assert output["verified"] is True


@patch("atrun.run.fetch_record")
@patch("atrun.verify.httpx.get")
def test_verify_mismatch(mock_verify_get, mock_fetch):
    from tests.conftest import mock_response

    mock_fetch.return_value = _make_record("cowsay", "1.6.0", "sha256:0000", "https://example.com/cowsay.tgz")
    mock_verify_get.return_value = mock_response(content=b"wrong content")

    runner = CliRunner()
    result = runner.invoke(cli, ["verify", "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 1


@patch("atrun.run.fetch_record")
@patch("atrun.run.fetch_yanks", return_value={})
def test_info_json(mock_yanks, mock_fetch):
    mock_fetch.return_value = _make_record("cowsay", "1.6.0", "sha256:abc", "https://example.com/cowsay.tgz")

    runner = CliRunner()
    result = runner.invoke(cli, ["info", "--json", "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert "at" in output
    assert "content" in output
    assert output["content"]["package"] == "cowsay"


@patch("atrun.run.fetch_record")
def test_resolve(mock_fetch):
    mock_fetch.return_value = _make_record(
        "cowsay", "1.6.0", "sha256:abc",
        "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["resolve", "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    assert "cowsay" in result.output


@patch("atrun.run.fetch_record")
@patch("atrun.run.fetch_yanks", return_value={})
def test_install_dry_run(mock_yanks, mock_fetch):
    mock_fetch.return_value = _make_record(
        "ripgrep", "14.1.0", "sha256:abc",
        "https://crates.io/api/v1/crates/ripgrep/14.1.0/download",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["install", "--dry-run", "--no-verify", "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    assert "cargo" in result.output


@patch("atrun.run.fetch_record")
@patch("atrun.publish.build_record")
def test_publish_dry_run(mock_build, mock_fetch):
    mock_build.return_value = {
        "$type": "dev.atpub.manifest",
        "package": "cowsay",
        "version": "1.6.0",
        "resolved": [],
        "createdAt": "2024-01-01T00:00:00Z",
    }

    runner = CliRunner()
    result = runner.invoke(cli, ["publish", "--dry-run", "--dist-url", "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"])
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["package"] == "cowsay"
