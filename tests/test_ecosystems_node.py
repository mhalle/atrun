"""Tests for atrun.ecosystems.node — lockfile parsing, hash conversion, install/run args."""

from __future__ import annotations

import base64
import hashlib

from atrun.ecosystems.node import (
    _convert_sri_hash,
    _hex_to_sri,
    _verify_hash,
    generate_install_args,
    generate_requirements,
    parse_lockfile,
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
    # deps is now index-based; verify it points to string-width
    for idx in cowsay["dependencies"]:
        assert entries[idx]["name"] == "string-width"


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
    assert entries[0]["urls"] == ["https://registry.npmjs.org/foo/-/foo-1.0.0.tgz"]


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


def test_parse_lockfile_engines_metadata():
    content = '''{
      "lockfileVersion": 3,
      "packages": {
        "node_modules/foo": {
          "version": "1.0.0",
          "integrity": "sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
          "resolved": "https://registry.npmjs.org/foo/-/foo-1.0.0.tgz",
          "engines": {"node": ">=14"}
        }
      }
    }'''
    entries = parse_lockfile(content)
    assert len(entries) == 1
    assert entries[0]["metadata"] == {"node": ">=14"}


def test_parse_lockfile_no_metadata_without_engines(package_lock_json_content):
    entries = parse_lockfile(package_lock_json_content)
    assert all("metadata" not in e for e in entries)


def test_parse_lockfile_artifact_type(package_lock_json_content):
    entries = parse_lockfile(package_lock_json_content)
    assert all(e["artifactType"] == "tarball" for e in entries)


# --- generate_requirements ---


def test_generate_requirements_format():
    resolved = [
        {"name": "cowsay", "version": "1.6.0"},
        {"name": "string-width", "version": "4.2.3"},
    ]
    result = generate_requirements(resolved)
    assert "cowsay@1.6.0" in result
    assert "string-width@4.2.3" in result


# --- generate_install_args ---


def test_generate_install_args_uses_version():
    record = {
        "package": "cowsay",
        "artifacts": [
            {
                "name": "cowsay",
                "version": "1.6.0",
                "digest": "sha256:" + "ab" * 32,
                "urls": ["https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"],
            },
        ],
    }
    args = generate_install_args(record)
    assert args == ["pnpm", "install", "-g", "cowsay@1.6.0"]


def test_generate_install_args_custom_engine():
    record = {
        "package": "cowsay",
        "artifacts": [
            {
                "name": "cowsay",
                "version": "1.6.0",
                "digest": "sha256:" + "ab" * 32,
                "urls": ["https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"],
            },
        ],
    }
    args = generate_install_args(record, engine="npm")
    assert args == ["npm", "install", "-g", "cowsay@1.6.0"]
