"""Tests for atrun.purl — purl support layer."""

from unittest.mock import patch

import pytest

from atrun.purl import (
    build,
    detect_ecosystem,
    from_shorthand,
    parse,
    resolve,
)
from atrun.purl._resolve import (
    _extract_github,
    _extract_npm,
    _extract_pypi,
    resolve_digest,
    resolve_download_url,
)
from atrun.purl._unify import unify_metadata


# --- parse / build round-trips ---


def test_parse_pypi():
    p = parse("pkg:pypi/requests@2.31.0")
    assert p.type == "pypi"
    assert p.name == "requests"
    assert p.version == "2.31.0"


def test_build_pypi():
    assert build("pypi", "requests", "2.31.0") == "pkg:pypi/requests@2.31.0"


def test_build_no_version():
    assert build("pypi", "requests") == "pkg:pypi/requests"


def test_roundtrip_scoped_npm():
    purl = build("npm", "prettier", "3.0.0", namespace="@prettier")
    p = parse(purl)
    assert p.type == "npm"
    assert p.namespace == "@prettier"
    assert p.name == "prettier"
    assert p.version == "3.0.0"


def test_roundtrip_golang():
    purl = build("golang", "text", "v0.14.0", namespace="golang.org/x")
    p = parse(purl)
    assert p.type == "golang"
    assert p.namespace == "golang.org/x"
    assert p.name == "text"
    assert p.version == "v0.14.0"


# --- download URL extraction (mocked metadata) ---


def test_extract_pypi_prefers_wheel():
    from packageurl import PackageURL

    raw = {
        "urls": [
            {"url": "https://files.pythonhosted.org/foo-1.0.tar.gz"},
            {"url": "https://files.pythonhosted.org/foo-1.0-py3-none-any.whl"},
        ]
    }
    p = PackageURL.from_string("pkg:pypi/foo@1.0")
    assert _extract_pypi(p, raw) == "https://files.pythonhosted.org/foo-1.0-py3-none-any.whl"


def test_extract_pypi_falls_back_to_sdist():
    from packageurl import PackageURL

    raw = {
        "urls": [
            {"url": "https://files.pythonhosted.org/foo-1.0.tar.gz"},
        ]
    }
    p = PackageURL.from_string("pkg:pypi/foo@1.0")
    assert _extract_pypi(p, raw) == "https://files.pythonhosted.org/foo-1.0.tar.gz"


def test_extract_npm_tarball():
    from packageurl import PackageURL

    raw = {"dist": {"tarball": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz"}}
    p = PackageURL.from_string("pkg:npm/lodash@4.17.21")
    assert _extract_npm(p, raw) == "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz"


def test_extract_github_prefers_whl():
    from packageurl import PackageURL

    raw = {
        "assets": [
            {"name": "app.tar.gz", "browser_download_url": "https://github.com/x/y/app.tar.gz"},
            {"name": "app-1.0-py3-none-any.whl", "browser_download_url": "https://github.com/x/y/app.whl"},
        ]
    }
    p = PackageURL.from_string("pkg:github/x/y@v1.0")
    assert _extract_github(p, raw) == "https://github.com/x/y/app.whl"


def test_resolve_cargo_deterministic():
    url = resolve_download_url("pkg:cargo/serde@1.0.193")
    assert url == "https://crates.io/api/v1/crates/serde/1.0.193/download"


def test_resolve_golang_deterministic():
    url = resolve_download_url("pkg:golang/golang.org/x/text@v0.14.0")
    assert url == "https://proxy.golang.org/golang.org/x/text/@v/v0.14.0.zip"


def test_resolve_oci():
    url = resolve_download_url("pkg:docker/ghcr.io/user/app@1.0")
    assert url == "oci://ghcr.io/user/app:1.0"


def test_resolve_oci_bare_name():
    url = resolve_download_url("pkg:docker/nginx@1.25")
    assert url == "oci://docker.io/library/nginx:1.25"


def test_resolve_oci_user_name():
    url = resolve_download_url("pkg:docker/user/app@1.0")
    assert url == "oci://docker.io/user/app:1.0"


def test_resolve_oci_no_tag():
    url = resolve_download_url("pkg:docker/nginx")
    assert url == "oci://docker.io/library/nginx:latest"


def test_resolve_cargo_versionless():
    fake_raw = {"crate": {"max_version": "1.0.193"}}
    with patch("atrun.purl._resolve._get_raw_metadata", return_value=fake_raw):
        url = resolve_download_url("pkg:cargo/serde")
    assert url == "https://crates.io/api/v1/crates/serde/1.0.193/download"


def test_resolve_golang_versionless():
    import httpx

    fake_resp = httpx.Response(200, json={"Version": "v0.14.0"}, request=httpx.Request("GET", "https://proxy.golang.org/golang.org/x/text/@latest"))
    with patch("atrun.purl._resolve.httpx.get", return_value=fake_resp):
        url = resolve_download_url("pkg:golang/golang.org/x/text")
    assert url == "https://proxy.golang.org/golang.org/x/text/@v/v0.14.0.zip"


def test_resolve_pypi_mocked():
    fake_raw = {
        "urls": [
            {"url": "https://files.pythonhosted.org/pkg-1.0-py3-none-any.whl"},
        ]
    }
    with patch("atrun.purl._resolve._get_raw_metadata", return_value=fake_raw):
        url = resolve_download_url("pkg:pypi/pkg@1.0")
    assert url == "https://files.pythonhosted.org/pkg-1.0-py3-none-any.whl"


# --- unified metadata mapping (dict → dict, no mocking) ---


def test_unify_pypi():
    raw = {
        "info": {
            "name": "requests",
            "version": "2.31.0",
            "summary": "HTTP library",
            "license": "Apache-2.0",
            "home_page": "https://requests.readthedocs.io",
        }
    }
    result = unify_metadata("pkg:pypi/requests@2.31.0", raw)
    assert result["description"] == "HTTP library"
    assert result["license"] == "Apache-2.0"
    assert result["url"] == "https://requests.readthedocs.io"
    assert result["name"] == "requests"


def test_unify_pypi_project_urls_fallback():
    raw = {
        "info": {
            "name": "foo",
            "version": "1.0",
            "summary": "A thing",
            "license": "MIT",
            "home_page": None,
            "project_urls": {"Homepage": "https://foo.dev"},
        }
    }
    result = unify_metadata("pkg:pypi/foo@1.0", raw)
    assert result["url"] == "https://foo.dev"


def test_unify_npm():
    raw = {
        "name": "lodash",
        "version": "4.17.21",
        "description": "Utility library",
        "license": "MIT",
        "homepage": "https://lodash.com",
    }
    result = unify_metadata("pkg:npm/lodash@4.17.21", raw)
    assert result["description"] == "Utility library"
    assert result["license"] == "MIT"
    assert result["url"] == "https://lodash.com"


def test_unify_npm_repo_fallback():
    raw = {
        "name": "express",
        "description": "Web framework",
        "license": "MIT",
        "repository": {"url": "https://github.com/expressjs/express"},
    }
    result = unify_metadata("pkg:npm/express@4.18.0", raw)
    assert result["url"] == "https://github.com/expressjs/express"


def test_unify_cargo():
    raw = {
        "version": {
            "crate": "serde",
            "num": "1.0.193",
            "description": "Serialization framework",
            "license": "MIT OR Apache-2.0",
            "repository": "https://github.com/serde-rs/serde",
        }
    }
    result = unify_metadata("pkg:cargo/serde@1.0.193", raw)
    assert result["description"] == "Serialization framework"
    assert result["license"] == "MIT OR Apache-2.0"
    assert result["url"] == "https://github.com/serde-rs/serde"


def test_unify_github():
    raw = {
        "tag_name": "v1.0.0",
        "body": "First release",
        "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
        "license": {"spdx_id": "MIT"},
    }
    result = unify_metadata("pkg:github/owner/repo@v1.0.0", raw)
    assert result["description"] == "First release"
    assert result["license"] == "MIT"
    assert result["url"] == "https://github.com/owner/repo/releases/tag/v1.0.0"


def test_unify_golang():
    raw = {"Version": "v0.14.0", "Time": "2024-01-01T00:00:00Z"}
    result = unify_metadata("pkg:golang/golang.org/x/text@v0.14.0", raw)
    assert result["url"] == "https://pkg.go.dev/golang.org/x/text"
    assert result["version"] == "v0.14.0"


def test_unify_default_mapper():
    raw = {
        "name": "something",
        "description": "A package",
        "license": "BSD-3-Clause",
        "homepage": "https://example.com",
    }
    result = unify_metadata("pkg:generic/something@1.0", raw)
    assert result["description"] == "A package"
    assert result["license"] == "BSD-3-Clause"
    assert result["url"] == "https://example.com"


# --- shorthand compatibility ---


def test_shorthand_pypi():
    assert from_shorthand("pypi:requests@2.31") == "pkg:pypi/requests@2.31"


def test_shorthand_pypi_no_version():
    assert from_shorthand("pypi:requests") == "pkg:pypi/requests"


def test_shorthand_npm_simple():
    assert from_shorthand("npm:lodash@4.17.21") == "pkg:npm/lodash@4.17.21"


def test_shorthand_npm_scoped():
    result = from_shorthand("npm:@scope/pkg@1.0")
    p = parse(result)
    assert p.type == "npm"
    assert p.namespace == "@scope"
    assert p.name == "pkg"
    assert p.version == "1.0"


def test_shorthand_crate():
    assert from_shorthand("crate:serde@1.0") == "pkg:cargo/serde@1.0"


def test_shorthand_golang():
    result = from_shorthand("go:golang.org/x/text@v0.14")
    p = parse(result)
    assert p.type == "golang"
    assert p.namespace == "golang.org/x"
    assert p.name == "text"
    assert p.version == "v0.14"


def test_shorthand_github():
    result = from_shorthand("gh:owner/repo@v1.0")
    p = parse(result)
    assert p.type == "github"
    assert p.namespace == "owner"
    assert p.name == "repo"
    assert p.version == "v1.0"


def test_shorthand_docker():
    result = from_shorthand("docker:ghcr.io/user/app:1.0")
    p = parse(result)
    assert p.type == "docker"
    assert p.namespace == "ghcr.io/user"
    assert p.name == "app"
    assert p.version == "1.0"


def test_shorthand_unknown_prefix():
    with pytest.raises(ValueError, match="Unknown shorthand"):
        from_shorthand("unknown:foo@1.0")


# --- ecosystem detection ---


def test_detect_ecosystem_pypi():
    assert detect_ecosystem("pkg:pypi/foo@1.0") == "python"


def test_detect_ecosystem_cargo():
    assert detect_ecosystem("pkg:cargo/bar@2.0") == "rust"


def test_detect_ecosystem_npm():
    assert detect_ecosystem("pkg:npm/lodash@4.0") == "node"


def test_detect_ecosystem_golang():
    assert detect_ecosystem("pkg:golang/golang.org/x/text@v0.14") == "go"


def test_detect_ecosystem_docker():
    assert detect_ecosystem("pkg:docker/nginx@1.25") == "container"


def test_detect_ecosystem_github():
    assert detect_ecosystem("pkg:github/owner/repo@v1.0") is None


def test_detect_ecosystem_unknown():
    assert detect_ecosystem("pkg:generic/foo@1.0") is None


# --- resolve_digest (mocked metadata) ---


def test_resolve_digest_pypi():
    fake_raw = {
        "urls": [
            {
                "url": "https://files.pythonhosted.org/foo-1.0-py3-none-any.whl",
                "digests": {"sha256": "abcd1234" * 8},
            },
            {
                "url": "https://files.pythonhosted.org/foo-1.0.tar.gz",
                "digests": {"sha256": "eeee0000" * 8},
            },
        ]
    }
    with patch("atrun.purl._resolve._get_raw_metadata", return_value=fake_raw):
        result = resolve_digest("pkg:pypi/foo@1.0")
    # Should pick the wheel (preferred by _extract_pypi) and return its sha256
    assert result == f"sha256:{'abcd1234' * 8}"


def test_resolve_digest_npm():
    import base64

    # SRI format: sha512-<base64>
    raw_bytes = b"\x01\x02\x03" * 20  # 60 bytes
    b64 = base64.b64encode(raw_bytes).decode()
    expected_hex = raw_bytes.hex()

    fake_raw = {
        "dist": {
            "tarball": "https://registry.npmjs.org/bar/-/bar-2.0.tgz",
            "integrity": f"sha512-{b64}",
        }
    }
    with patch("atrun.purl._resolve._get_raw_metadata", return_value=fake_raw):
        result = resolve_digest("pkg:npm/bar@2.0")
    assert result == f"sha512:{expected_hex}"


def test_resolve_digest_cargo_returns_none():
    assert resolve_digest("pkg:cargo/serde@1.0.193") is None


def test_resolve_digest_unknown_returns_none():
    assert resolve_digest("pkg:generic/foo@1.0") is None
