"""Tests for atrun.cli — CliRunner integration tests."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from atrun.cli import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Social package distribution" in result.output


def _make_record(package, version, hash_str, url, extra_resolved=None):
    """Helper to build a fetch_record-style return value."""
    artifacts = [{"name": package, "version": version, "digest": hash_str, "urls": [url]}]
    if extra_resolved:
        artifacts.extend(extra_resolved)
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
            "artifacts": artifacts,
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
@patch("atrun.run.fetch_yanks", return_value={})
def test_install_dry_run_node_uses_version(mock_yanks, mock_fetch):
    mock_fetch.return_value = _make_record(
        "cowsay", "1.6.0", "sha256:abc",
        "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["install", "--dry-run", "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    assert "cowsay@1.6.0" in result.output
    assert "pnpm install -g" in result.output


def _mock_httpx_client(data):
    """Create a mock httpx.Client context manager whose get() returns data."""
    from tests.conftest import mock_response
    client = MagicMock()
    client.get.return_value = mock_response(content=data)
    client.__enter__ = lambda s: client
    client.__exit__ = lambda s, *a: None
    return client


@patch("atrun.run.fetch_record")
@patch("atrun.cli.httpx.Client")
def test_fetch_main_artifact(mock_client_cls, mock_fetch, tmp_path):
    data = b"tarball content"
    digest = hashlib.sha256(data).hexdigest()
    mock_fetch.return_value = _make_record(
        "cowsay", "1.6.0", f"sha256:{digest}",
        "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
    )
    mock_client_cls.return_value = _mock_httpx_client(data)

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch", "-d", str(tmp_path), "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    assert (tmp_path / "cowsay-1.6.0.tgz").exists()
    assert (tmp_path / "cowsay-1.6.0.tgz").read_bytes() == data


@patch("atrun.run.fetch_record")
@patch("atrun.cli.httpx.Client")
def test_fetch_with_deps(mock_client_cls, mock_fetch, tmp_path):
    data = b"tarball content"
    digest = hashlib.sha256(data).hexdigest()
    record = _make_record(
        "cowsay", "1.6.0", f"sha256:{digest}",
        "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
        extra_resolved=[{
            "name": "string-width", "version": "4.2.3",
            "digest": f"sha256:{digest}",
            "urls": ["https://registry.npmjs.org/string-width/-/string-width-4.2.3.tgz"],
        }],
    )
    mock_fetch.return_value = record
    mock_client_cls.return_value = _mock_httpx_client(data)

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch", "--deps", "-d", str(tmp_path), "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    assert (tmp_path / "cowsay-1.6.0.tgz").exists()
    assert (tmp_path / "string-width-4.2.3.tgz").exists()


@patch("atrun.run.fetch_record")
@patch("atrun.cli.httpx.Client")
def test_fetch_hash_mismatch_fails(mock_client_cls, mock_fetch, tmp_path):
    mock_fetch.return_value = _make_record(
        "cowsay", "1.6.0", "sha256:" + "00" * 32,
        "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
    )
    mock_client_cls.return_value = _mock_httpx_client(b"wrong content")

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch", "-d", str(tmp_path), "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 1
    assert not (tmp_path / "cowsay-1.6.0.tgz").exists()


@patch("atrun.run.fetch_record")
@patch("atrun.cli.httpx.Client")
def test_fetch_no_verify(mock_client_cls, mock_fetch, tmp_path):
    data = b"content"
    mock_fetch.return_value = _make_record(
        "cowsay", "1.6.0", "sha256:" + "00" * 32,
        "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
    )
    mock_client_cls.return_value = _mock_httpx_client(data)

    runner = CliRunner()
    result = runner.invoke(cli, ["fetch", "--no-verify", "-d", str(tmp_path), "at://did:plc:abc/dev.atpub.manifest/3mgxyz"])
    assert result.exit_code == 0
    assert (tmp_path / "cowsay-1.6.0.tgz").exists()


@patch("atrun.publish.build_record")
def test_publish_dry_run(mock_build):
    mock_build.return_value = {
        "$type": "dev.atpub.manifest",
        "package": "cowsay",
        "version": "1.6.0",
        "artifacts": [],
        "createdAt": "2024-01-01T00:00:00Z",
    }

    runner = CliRunner()
    result = runner.invoke(cli, ["publish", "--dry-run", "--dist-url", "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["package"] == "cowsay"
    # Verify build_record received dist_urls as a tuple
    _, kwargs = mock_build.call_args
    assert kwargs.get("dist_urls") == ("https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",)


@patch("atrun.publish.build_record")
def test_publish_dry_run_multiple_urls(mock_build):
    mock_build.return_value = {
        "$type": "dev.atpub.manifest",
        "package": "requests",
        "version": "2.31.0",
        "artifacts": [],
        "createdAt": "2024-01-01T00:00:00Z",
    }

    runner = CliRunner()
    result = runner.invoke(cli, [
        "publish", "--dry-run",
        "--dist-url", "pkg:pypi/requests@2.31.0",
        "--dist-url", "https://github.com/psf/requests/archive/v2.31.0.tar.gz",
    ])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_build.call_args
    assert kwargs.get("dist_urls") == (
        "pkg:pypi/requests@2.31.0",
        "https://github.com/psf/requests/archive/v2.31.0.tar.gz",
    )


@patch("atrun.publish.build_record")
def test_publish_dry_run_metadata_flags(mock_build):
    mock_build.return_value = {
        "$type": "dev.atpub.manifest",
        "package": "cowsay",
        "version": "1.6.0",
        "artifacts": [],
        "createdAt": "2024-01-01T00:00:00Z",
    }

    runner = CliRunner()
    result = runner.invoke(cli, [
        "publish", "--dry-run",
        "--dist-url", "npm:cowsay",
        "--description", "ASCII cow",
        "--license", "MIT",
        "--url", "https://example.com",
    ])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_build.call_args
    assert kwargs.get("description") == "ASCII cow"
    assert kwargs.get("license") == "MIT"
    assert kwargs.get("url") == "https://example.com"
