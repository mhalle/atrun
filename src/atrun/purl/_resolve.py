"""Download URL extraction from raw registry metadata."""

from __future__ import annotations

import re

import httpx
from packageurl import PackageURL
from purl2meta import get_metadata as _get_raw_metadata


def resolve_download_url(purl: str) -> str | None:
    """Fetch metadata via purl2meta, then extract the download URL."""
    p = PackageURL.from_string(purl)

    # Some types have deterministic URLs — no fetch needed
    if p.type == "cargo":
        return _extract_cargo(p, purl)
    if p.type == "golang":
        return _extract_golang(p)
    if p.type in ("docker", "oci"):
        return _extract_oci(p)

    raw = _get_raw_metadata(purl)
    if raw is None:
        return None

    extractor = _EXTRACTORS.get(p.type)
    if extractor:
        return extractor(p, raw)
    return None


def _extract_pypi(p: PackageURL, raw: dict) -> str | None:
    """Pick download URL from PyPI metadata.

    Preference order:
      1. Platform-compatible wheel (matching current OS/arch)
      2. Universal wheel (py3-none-any)
      3. sdist (.tar.gz)
      4. First available URL
    """
    import platform as _platform
    import sysconfig as _sysconfig

    urls = raw.get("urls", [])
    wheels = [u for u in urls if u["url"].endswith(".whl")]

    if wheels:
        # Build a set of compatible platform tags
        plat = _sysconfig.get_platform().replace("-", "_").replace(".", "_")
        compatible = set()
        compatible.add("any")
        compatible.add(plat)
        # macOS: add macosx_NN_0_arm64 / macosx_NN_0_universal2 variants
        if _platform.system() == "Darwin":
            arch = _platform.machine()
            ver = _platform.mac_ver()[0]
            major = int(ver.split(".")[0]) if ver else 10
            for v in range(major, 9, -1):
                compatible.add(f"macosx_{v}_0_{arch}")
                compatible.add(f"macosx_{v}_0_universal2")

        # Find a compatible wheel
        for u in wheels:
            filename = u["url"].rsplit("/", 1)[-1]
            # Wheel filename: {name}-{ver}(-{build})?-{pytag}-{abitag}-{plattag}.whl
            parts = filename[:-4].split("-")
            plat_tag = parts[-1] if len(parts) >= 3 else ""
            for tag in plat_tag.split("."):
                if tag in compatible:
                    return u["url"]

        # No platform match — try universal wheels
        for u in wheels:
            if "-none-any.whl" in u["url"]:
                return u["url"]

    for u in urls:
        if u["url"].endswith(".tar.gz"):
            return u["url"]
    if urls:
        return urls[0]["url"]
    return None


def _extract_npm(p: PackageURL, raw: dict) -> str | None:
    """Pick tarball URL from npm metadata."""
    # Version-specific endpoint returns dist.tarball directly
    tarball = raw.get("dist", {}).get("tarball")
    if tarball:
        return tarball
    # Full package endpoint: resolve via dist-tags then versions
    version = p.version
    if not version:
        version = raw.get("dist-tags", {}).get("latest")
    if version:
        return raw.get("versions", {}).get(version, {}).get("dist", {}).get("tarball")
    return None


def _extract_cargo(p: PackageURL, purl: str) -> str | None:
    """Construct deterministic crates.io download URL."""
    version = p.version
    if not version:
        raw = _get_raw_metadata(purl)
        if not isinstance(raw, dict):
            return None
        version = raw.get("crate", {}).get("max_version")
        if not version:
            return None
    return f"https://crates.io/api/v1/crates/{p.name}/{version}/download"


def _extract_golang(p: PackageURL) -> str | None:
    """Construct deterministic Go proxy download URL."""
    module = f"{p.namespace}/{p.name}" if p.namespace else p.name
    escaped = re.sub(r"[A-Z]", lambda m: f"!{m.group().lower()}", module)
    version = p.version
    if not version:
        resp = httpx.get(f"https://proxy.golang.org/{escaped}/@latest")
        resp.raise_for_status()
        version = resp.json().get("Version")
        if not version:
            return None
    return f"https://proxy.golang.org/{escaped}/@v/{version}.zip"


def _extract_github(p: PackageURL, raw: dict) -> str | None:
    """Pick download URL from GitHub release assets."""
    # Check extensions in priority order: .whl > .tgz > .tar.gz
    assets = raw.get("assets", [])
    for ext in (".whl", ".tgz", ".tar.gz"):
        for asset in assets:
            if asset["name"].endswith(ext):
                return asset["browser_download_url"]
    # Fall back to first asset
    if assets:
        return assets[0]["browser_download_url"]
    return None


def _extract_oci(p: PackageURL) -> str | None:
    """Construct oci:// URL from purl components.

    Normalizes Docker Hub references:
      - bare name (nginx) → docker.io/library/nginx
      - user/name → docker.io/user/name
      - full registry (ghcr.io/user/app) → unchanged
    """
    name = f"{p.namespace}/{p.name}" if p.namespace else p.name
    # Normalize Docker Hub references
    if "/" not in name:
        # Bare image name like "nginx"
        name = f"docker.io/library/{name}"
    elif "." not in name.split("/")[0]:
        # user/app (no registry domain) → docker.io/user/app
        name = f"docker.io/{name}"
    tag = p.version or "latest"
    return f"oci://{name}:{tag}"


_EXTRACTORS = {
    "pypi": _extract_pypi,
    "npm": _extract_npm,
    "github": _extract_github,
}


def resolve_digest(purl: str) -> str | None:
    """Extract artifact digest from registry metadata without downloading.

    Returns 'algo:hex' string or None if the registry doesn't provide hashes.
    Supports PyPI (sha256 from urls[].digests) and npm (sha512 from dist.integrity).
    """
    import base64

    p = PackageURL.from_string(purl)

    if p.type == "pypi":
        raw = _get_raw_metadata(purl)
        if not isinstance(raw, dict):
            return None
        download_url = _extract_pypi(p, raw)
        if not download_url:
            return None
        for u in raw.get("urls", []):
            if u.get("url") == download_url:
                sha256 = u.get("digests", {}).get("sha256")
                if sha256:
                    return f"sha256:{sha256}"
        return None

    if p.type == "npm":
        raw = _get_raw_metadata(purl)
        if not isinstance(raw, dict):
            return None
        # Version-specific endpoint: dist.integrity directly
        integrity = raw.get("dist", {}).get("integrity")
        # Full package endpoint: resolve via versions
        if not integrity:
            version = p.version
            if not version:
                version = raw.get("dist-tags", {}).get("latest")
            if version:
                integrity = (
                    raw.get("versions", {})
                    .get(version, {})
                    .get("dist", {})
                    .get("integrity")
                )
        if integrity and integrity.startswith("sha512-"):
            b64 = integrity[len("sha512-"):]
            hex_digest = base64.b64decode(b64).hex()
            return f"sha512:{hex_digest}"
        return None

    # cargo, golang, github, oci: no digest in metadata API
    return None
