"""Tests for atrun.ecosystems.node — lockfile parsing, hash conversion, install/run args."""

from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from atrun.ecosystems.node import (
    _build_pnpm_lockfile,
    _convert_sri_hash,
    _hex_to_sri,
    _verify_hash,
    generate_install_args,
    generate_requirements,
    parse_lockfile,
    run_verified_install,
)


# --- Hash conversion ---


def test_hex_to_sri():
    hex_hash = hashlib.sha512(b"test").hexdigest()
    sri = _hex_to_sri(f"sha512:{hex_hash}")
    assert sri.startswith("sha512-")
    # Roundtrip: decode the base64 part back to hex
    b64_part = sri.split("-", 1)[1]
    assert base64.b64decode(b64_part).hex() == hex_hash


def test_convert_sri_hash_sri_format():
    raw = hashlib.sha512(b"hello").digest()
    b64 = base64.b64encode(raw).decode()
    result = _convert_sri_hash(f"sha512-{b64}")
    assert result.startswith("sha512:")
    assert result == f"sha512:{raw.hex()}"


def test_convert_sri_hash_passthrough():
    assert _convert_sri_hash("sha256:abc123") == "sha256:abc123"


def test_verify_hash_correct():
    data = b"hello"
    digest = hashlib.sha256(data).hexdigest()
    assert _verify_hash(data, f"sha256:{digest}") is True


def test_verify_hash_wrong():
    assert _verify_hash(b"hello", "sha256:0000000000000000") is False


# --- parse_lockfile ---


def test_parse_lockfile_basic(package_lock_json_content):
    entries = parse_lockfile(package_lock_json_content)
    assert len(entries) == 2
    names = [e["name"] for e in entries]
    assert "cowsay" in names
    assert "string-width" in names


def test_parse_lockfile_sorted(package_lock_json_content):
    entries = parse_lockfile(package_lock_json_content)
    names = [e["name"] for e in entries]
    assert names == sorted(names)


def test_parse_lockfile_resolves_deps(package_lock_json_content):
    entries = parse_lockfile(package_lock_json_content)
    cowsay = next(e for e in entries if e["name"] == "cowsay")
    assert "dependencies" in cowsay
    assert any("string-width@" in d for d in cowsay["dependencies"])


def test_parse_lockfile_skips_root(package_lock_json_content):
    entries = parse_lockfile(package_lock_json_content)
    names = [e["name"] for e in entries]
    assert "myapp" not in names


def test_parse_lockfile_constructs_url_when_missing():
    content = '''{
      "lockfileVersion": 3,
      "packages": {
        "node_modules/foo": {
          "version": "1.0.0",
          "integrity": "sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        }
      }
    }'''
    entries = parse_lockfile(content)
    assert len(entries) == 1
    assert entries[0]["url"] == "https://registry.npmjs.org/foo/-/foo-1.0.0.tgz"


def test_parse_lockfile_deduplicates():
    content = '''{
      "lockfileVersion": 3,
      "packages": {
        "node_modules/foo": {
          "version": "1.0.0",
          "integrity": "sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
          "resolved": "https://registry.npmjs.org/foo/-/foo-1.0.0.tgz"
        },
        "node_modules/bar/node_modules/foo": {
          "version": "1.0.0",
          "integrity": "sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
          "resolved": "https://registry.npmjs.org/foo/-/foo-1.0.0.tgz"
        }
      }
    }'''
    entries = parse_lockfile(content)
    foo_entries = [e for e in entries if e["name"] == "foo"]
    assert len(foo_entries) == 1


# --- generate_requirements ---


def test_generate_requirements_format():
    resolved = [
        {"name": "cowsay", "version": "1.6.0"},
        {"name": "string-width", "version": "4.2.3"},
    ]
    result = generate_requirements(resolved)
    assert "cowsay@1.6.0" in result
    assert "string-width@4.2.3" in result


# --- _build_pnpm_lockfile ---


@patch("atrun.ecosystems.node._check_engine")
def test_generate_install_args_uses_url(mock_check):
    record = {
        "package": "cowsay",
        "resolved": [
            {
                "name": "cowsay",
                "version": "1.6.0",
                "hash": "sha256:" + "ab" * 32,
                "url": "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
            },
        ],
    }
    args = generate_install_args(record)
    assert args[-1] == "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"
    assert "cowsay@1.6.0" not in args


def test_build_pnpm_lockfile():
    record = {
        "package": "cowsay",
        "resolved": [
            {
                "name": "cowsay",
                "version": "1.6.0",
                "hash": "sha256:" + "ab" * 32,
                "url": "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
                "dependencies": ["string-width@4.2.3"],
            },
            {
                "name": "string-width",
                "version": "4.2.3",
                "hash": "sha256:" + "cd" * 32,
                "url": "https://registry.npmjs.org/string-width/-/string-width-4.2.3.tgz",
            },
        ],
    }
    import yaml
    result = _build_pnpm_lockfile(record)
    parsed = yaml.safe_load(result)
    assert parsed["lockfileVersion"] == "9.0"
    assert "cowsay@1.6.0" in parsed["packages"]
    assert "string-width@4.2.3" in parsed["packages"]


# --- run_verified_install (artifact verification after frozen-lockfile) ---


def _make_deps_record(package, version, hash_str, url):
    """Build a record with dependency data (triggers the --deps path)."""
    return {
        "package": package,
        "resolved": [
            {
                "name": package,
                "version": version,
                "hash": hash_str,
                "url": url,
                "dependencies": ["string-width@4.2.3"],
            },
            {
                "name": "string-width",
                "version": "4.2.3",
                "hash": "sha256:" + "cd" * 32,
                "url": "https://registry.npmjs.org/string-width/-/string-width-4.2.3.tgz",
            },
        ],
    }


@patch("atrun.ecosystems.node._check_engine")
@patch("atrun.ecosystems.node.subprocess.run")
@patch("atrun.ecosystems.node._build_pnpm_lockfile", return_value="lockfileVersion: '9.0'\n")
@patch("atrun.verify.httpx.get")
def test_run_verified_install_verifies_artifact_and_uses_file_url(
    mock_verify_get, mock_build_lock, mock_subproc, mock_engine
):
    """After frozen-lockfile, the artifact at pkg_entry['url'] is hash-verified
    and the global install uses a file:// path to the verified local copy."""
    import hashlib
    from pathlib import Path
    from tests.conftest import mock_response

    data = b"tarball content"
    digest = hashlib.sha256(data).hexdigest()
    url = "https://github.com/example/cowsay/releases/download/v1.6.0/cowsay-1.6.0.tgz"
    record = _make_deps_record("cowsay", "1.6.0", f"sha256:{digest}", url)

    mock_verify_get.return_value = mock_response(content=data)

    run_verified_install(record)

    # First subprocess.run call: pnpm install --frozen-lockfile (in tmpdir)
    # Second subprocess.run call: global install with file:// path
    assert mock_subproc.call_count == 2
    global_install_call = mock_subproc.call_args_list[1]
    global_install_cmd = global_install_call[0][0]
    assert global_install_cmd[0] == "pnpm"
    assert global_install_cmd[1] == "install"
    assert global_install_cmd[2] == "-g"
    assert global_install_cmd[3].startswith("file://")
    assert global_install_cmd[3].endswith(".tgz")

    # Verified temp file should be cleaned up
    verified_file = Path(global_install_cmd[3].removeprefix("file://"))
    assert not verified_file.exists()


@patch("atrun.ecosystems.node._check_engine")
@patch("atrun.ecosystems.node.subprocess.run")
@patch("atrun.ecosystems.node._build_pnpm_lockfile", return_value="lockfileVersion: '9.0'\n")
@patch("atrun.verify.httpx.get")
def test_run_verified_install_hash_mismatch_raises(
    mock_verify_get, mock_build_lock, mock_subproc, mock_engine
):
    """If the artifact at pkg_entry['url'] doesn't match the manifest hash,
    SystemExit is raised and no global install happens."""
    from tests.conftest import mock_response

    url = "https://github.com/example/cowsay/releases/download/v1.6.0/cowsay-1.6.0.tgz"
    record = _make_deps_record("cowsay", "1.6.0", "sha256:" + "00" * 32, url)

    mock_verify_get.return_value = mock_response(content=b"different content")

    with pytest.raises(SystemExit, match="Hash mismatch"):
        run_verified_install(record)

    # Only the frozen-lockfile call should have run, not the global install
    assert mock_subproc.call_count == 1


@patch("atrun.ecosystems.node._check_engine")
@patch("atrun.ecosystems.node.subprocess.run")
@patch("atrun.ecosystems.node._build_pnpm_lockfile", return_value="lockfileVersion: '9.0'\n")
def test_run_verified_install_no_hash_uses_raw_url(
    mock_build_lock, mock_subproc, mock_engine
):
    """When the record has no hash, the global install uses the raw URL
    without download_and_verify."""
    record = {
        "package": "cowsay",
        "resolved": [
            {
                "name": "cowsay",
                "version": "1.6.0",
                "hash": "",
                "url": "https://example.com/cowsay-1.6.0.tgz",
                "dependencies": ["string-width@4.2.3"],
            },
            {
                "name": "string-width",
                "version": "4.2.3",
                "hash": "sha256:" + "cd" * 32,
                "url": "https://registry.npmjs.org/string-width/-/string-width-4.2.3.tgz",
            },
        ],
    }

    run_verified_install(record)

    assert mock_subproc.call_count == 2
    global_install_cmd = mock_subproc.call_args_list[1][0][0]
    assert global_install_cmd[3] == "https://example.com/cowsay-1.6.0.tgz"


@patch("atrun.ecosystems.node._check_engine")
@patch("atrun.ecosystems.node.subprocess.run")
@patch("atrun.ecosystems.node._build_pnpm_lockfile", return_value="lockfileVersion: '9.0'\n")
@patch("atrun.verify.httpx.get")
def test_run_verified_install_cleans_up_on_install_failure(
    mock_verify_get, mock_build_lock, mock_subproc, mock_engine
):
    """The verified temp file is cleaned up even if the global install fails."""
    import hashlib
    from tests.conftest import mock_response

    data = b"tarball content"
    digest = hashlib.sha256(data).hexdigest()
    url = "https://example.com/cowsay-1.6.0.tgz"
    record = _make_deps_record("cowsay", "1.6.0", f"sha256:{digest}", url)

    mock_verify_get.return_value = mock_response(content=data)
    # frozen-lockfile succeeds, global install fails
    mock_subproc.side_effect = [None, subprocess.CalledProcessError(1, "pnpm")]

    with pytest.raises(subprocess.CalledProcessError):
        run_verified_install(record)

    # The verified file should still be cleaned up via finally block
    assert mock_subproc.call_count == 2
    global_install_cmd = mock_subproc.call_args_list[1][0][0]
    verified_file = Path(global_install_cmd[3].removeprefix("file://"))
    assert not verified_file.exists()
