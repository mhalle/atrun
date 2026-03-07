"""Tests for atrun.ecosystems — detection functions and registry."""

from __future__ import annotations

import pytest

from atrun.ecosystems import (
    PACKAGE_TYPE_TO_ECOSYSTEM,
    PACKAGE_TYPES,
    detect_ecosystem_from_lockfile,
    detect_ecosystem_from_lockfile_path,
    detect_ecosystem_from_artifacts,
    detect_ecosystem_from_url,
    get_ecosystem,
)


# --- detect_ecosystem_from_url ---


def test_detect_url_npm():
    assert detect_ecosystem_from_url("https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz") == "node"


def test_detect_url_pypi():
    assert detect_ecosystem_from_url("https://files.pythonhosted.org/packages/click-8.1.7-py3-none-any.whl") == "python"


def test_detect_url_whl():
    assert detect_ecosystem_from_url("https://example.com/pkg-1.0-py3-none-any.whl") == "python"


def test_detect_url_crates():
    assert detect_ecosystem_from_url("https://crates.io/api/v1/crates/ripgrep/14.1.0/download") == "rust"


def test_detect_url_golang():
    assert detect_ecosystem_from_url("https://proxy.golang.org/golang.org/x/text/@v/v0.14.0.zip") == "go"


def test_detect_url_unknown():
    assert detect_ecosystem_from_url("https://example.com/something.zip") is None


# --- detect_ecosystem_from_artifacts ---


def test_detect_resolved_npm():
    resolved = [{"url": "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"}]
    assert detect_ecosystem_from_artifacts(resolved) == "node"


def test_detect_resolved_empty():
    assert detect_ecosystem_from_artifacts([]) == "python"


def test_detect_resolved_with_package_type():
    """packageType in record overrides URL-based detection."""
    resolved = [{"url": "https://example.com/unknown.zip"}]
    record = {"packageType": "dev.atpub.defs#npmPackage", "artifacts": resolved}
    assert detect_ecosystem_from_artifacts(resolved, record=record) == "node"


def test_detect_resolved_package_type_priority():
    """packageType takes priority over URL pattern."""
    resolved = [{"url": "https://files.pythonhosted.org/packages/foo-1.0.whl"}]
    record = {"packageType": "dev.atpub.defs#npmPackage", "artifacts": resolved}
    assert detect_ecosystem_from_artifacts(resolved, record=record) == "node"


def test_detect_resolved_unknown_package_type_falls_back():
    """Unknown packageType falls back to URL detection."""
    resolved = [{"url": "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"}]
    record = {"packageType": "dev.atpub.defs#unknownType", "artifacts": resolved}
    assert detect_ecosystem_from_artifacts(resolved, record=record) == "node"


# --- detect_ecosystem_from_lockfile ---


def test_detect_lockfile_python(pylock_toml_content):
    assert detect_ecosystem_from_lockfile(pylock_toml_content) == "python"


def test_detect_lockfile_node(package_lock_json_content):
    assert detect_ecosystem_from_lockfile(package_lock_json_content) == "node"


def test_detect_lockfile_rust(cargo_lock_content):
    assert detect_ecosystem_from_lockfile(cargo_lock_content) == "rust"


def test_detect_lockfile_go(go_sum_content):
    assert detect_ecosystem_from_lockfile(go_sum_content) == "go"


def test_detect_lockfile_unknown():
    # Content that fails TOML, JSON, and go.sum detection
    # (go.sum lines must have exactly 3 space-separated fields with h1: prefix)
    with pytest.raises(SystemExit):
        detect_ecosystem_from_lockfile("not a lockfile\nfoo bar baz\n")


# --- detect_ecosystem_from_lockfile_path ---


def test_detect_path_cargo():
    assert detect_ecosystem_from_lockfile_path("Cargo.lock") == "rust"


def test_detect_path_go_sum():
    assert detect_ecosystem_from_lockfile_path("go.sum") == "go"


def test_detect_path_unknown():
    assert detect_ecosystem_from_lockfile_path("requirements.txt") is None


# --- get_ecosystem ---


def test_get_ecosystem_python():
    mod = get_ecosystem("python")
    assert hasattr(mod, "parse_lockfile")


def test_get_ecosystem_node():
    mod = get_ecosystem("node")
    assert hasattr(mod, "parse_lockfile")


def test_get_ecosystem_unknown():
    with pytest.raises(SystemExit, match="Unknown ecosystem"):
        get_ecosystem("java")


# --- PACKAGE_TYPES ---


def test_package_types_keys():
    assert set(PACKAGE_TYPES.keys()) == {"python", "node", "rust", "go", "container"}


# --- container detection ---


def test_detect_url_oci():
    assert detect_ecosystem_from_url("oci://ghcr.io/user/app:1.0.0") == "container"


def test_detect_lockfile_path_compose_yml():
    assert detect_ecosystem_from_lockfile_path("compose.yml") == "container"


def test_detect_lockfile_path_docker_compose_yml():
    assert detect_ecosystem_from_lockfile_path("docker-compose.yml") == "container"


def test_detect_lockfile_path_images():
    assert detect_ecosystem_from_lockfile_path("mystack.images") == "container"


def test_detect_lockfile_compose_yaml():
    content = "services:\n  web:\n    image: nginx:1.25\n"
    assert detect_ecosystem_from_lockfile(content) == "container"


def test_detect_resolved_container_package_type():
    resolved = [{"url": "oci://ghcr.io/user/app:1.0.0"}]
    record = {"packageType": "dev.atpub.defs#container", "artifacts": resolved}
    assert detect_ecosystem_from_artifacts(resolved, record=record) == "container"


def test_get_ecosystem_container():
    mod = get_ecosystem("container")
    assert hasattr(mod, "parse_lockfile")
    assert hasattr(mod, "generate_install_args")
