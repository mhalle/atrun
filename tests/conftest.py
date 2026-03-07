"""Shared fixtures and helpers for atrun tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def pylock_toml_content():
    return '''\
lock-version = 1

[[packages]]
name = "click"
version = "8.1.7"

[[packages.wheels]]
url = "https://files.pythonhosted.org/packages/click-8.1.7-py3-none-any.whl"

[packages.wheels.hashes]
sha256 = "ae74fb96c20a0277a1d615f1e4d73c8414f5a98db8b799a7931d1582f3390c28"

[[packages]]
name = "httpx"
version = "0.27.0"

[[packages.wheels]]
url = "https://files.pythonhosted.org/packages/httpx-0.27.0-py3-none-any.whl"

[packages.wheels.hashes]
sha256 = "71d5465162c13681bff01ad59b2cc68dd838ea1f10e51574bac27103f00c91a5"
'''


@pytest.fixture
def pylock_toml_sha512():
    return '''\
lock-version = 1

[[packages]]
name = "foo"
version = "1.0.0"

[[packages.wheels]]
url = "https://example.com/foo-1.0.0-py3-none-any.whl"

[packages.wheels.hashes]
sha512 = "abcdef1234567890"
'''


@pytest.fixture
def pylock_toml_sdist():
    return '''\
lock-version = 1

[[packages]]
name = "bar"
version = "2.0.0"

[packages.sdist]
url = "https://example.com/bar-2.0.0.tar.gz"

[packages.sdist.hashes]
sha256 = "deadbeef"
'''


@pytest.fixture
def package_lock_json_content():
    return '''\
{
  "name": "myapp",
  "version": "1.0.0",
  "lockfileVersion": 3,
  "packages": {
    "": {
      "name": "myapp",
      "version": "1.0.0",
      "dependencies": {
        "cowsay": "^1.6.0"
      }
    },
    "node_modules/cowsay": {
      "version": "1.6.0",
      "resolved": "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
      "integrity": "sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
      "dependencies": {
        "string-width": "^4.2.3"
      }
    },
    "node_modules/string-width": {
      "version": "4.2.3",
      "resolved": "https://registry.npmjs.org/string-width/-/string-width-4.2.3.tgz",
      "integrity": "sha512-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=="
    }
  }
}
'''


@pytest.fixture
def cargo_lock_content():
    return '''\
[[package]]
name = "aho-corasick"
version = "1.1.2"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "b2969dcb958b36655471fc61f7e416fa76033bdd4bfed0678d8fee1e2d07a1f0"

[[package]]
name = "ripgrep"
version = "14.1.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "33d1246ff9295e2e25a0b4a5e1bbd2e78f026a7c3dbfe72f6a353882e993e48a"
dependencies = ["aho-corasick 1.1.2"]
'''


@pytest.fixture
def go_sum_content():
    return '''\
golang.org/x/text v0.14.0 h1:ScX5w1eTa3QqT8oi6+ziP7dTV1S2+ALU0bI+0zXKWiQ=
golang.org/x/text v0.14.0/go.mod h1:18ZOQIKpY8NJVqYksKHtTdi31H5itFRjB5/qKTNYzSU=
golang.org/x/net v0.20.0 h1:AQyQV4dYCvJ7vGmJyKki9+w=
'''


@pytest.fixture
def sample_manifest_record():
    return {
        "$type": "dev.atpub.manifest",
        "package": "cowsay",
        "version": "1.6.0",
        "resolved": [
            {
                "name": "cowsay",
                "version": "1.6.0",
                "hash": "sha512:0000000000000000",
                "url": "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz",
            },
            {
                "name": "string-width",
                "version": "4.2.3",
                "hash": "sha512:1111111111111111",
                "url": "https://registry.npmjs.org/string-width/-/string-width-4.2.3.tgz",
            },
        ],
    }


def mock_response(content=b"", json_data=None, status_code=200):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = content.decode() if isinstance(content, bytes) else content
    if json_data is not None:
        resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp
