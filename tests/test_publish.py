"""Tests for atrun.publish — filename and URL parsing."""

from __future__ import annotations

import pytest

from atrun.publish import _name_version_from_dist_filename, _name_version_from_dist_url


# --- _name_version_from_dist_filename ---


def test_filename_wheel():
    assert _name_version_from_dist_filename("atrun-0.5.0-py3-none-any.whl") == ("atrun", "0.5.0")


def test_filename_tar_gz():
    assert _name_version_from_dist_filename("foo-1.2.3.tar.gz") == ("foo", "1.2.3")


def test_filename_tgz():
    assert _name_version_from_dist_filename("cowsay-1.6.0.tgz") == ("cowsay", "1.6.0")


def test_filename_no_version():
    with pytest.raises(SystemExit, match="Cannot parse"):
        _name_version_from_dist_filename("noversion")


# --- _name_version_from_dist_url ---


def test_url_crates_io():
    assert _name_version_from_dist_url(
        "https://crates.io/api/v1/crates/ripgrep/14.1.0/download"
    ) == ("ripgrep", "14.1.0")


def test_url_golang_proxy():
    assert _name_version_from_dist_url(
        "https://proxy.golang.org/golang.org/x/text/@v/v0.14.0.zip"
    ) == ("golang.org/x/text", "v0.14.0")


def test_url_npm_fallback_to_filename():
    name, version = _name_version_from_dist_url(
        "https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz"
    )
    assert name == "cowsay"
    assert version == "1.6.0"


def test_url_golang_uppercase_escape():
    name, version = _name_version_from_dist_url(
        "https://proxy.golang.org/github.com/!azure/azure-sdk/@v/v1.0.0.zip"
    )
    assert name == "github.com/Azure/azure-sdk"
    assert version == "v1.0.0"
