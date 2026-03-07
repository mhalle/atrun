"""Tests for atrun.ecosystems.node — lockfile parsing, hash conversion, install/run args."""

from __future__ import annotations

import base64
import hashlib

import pytest

from atrun.ecosystems.node import (
    _build_pnpm_lockfile,
    _convert_sri_hash,
    _hex_to_sri,
    _verify_hash,
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
