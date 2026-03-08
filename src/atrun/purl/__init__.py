"""Package URL (purl) support for atrun, built on purl2meta."""

from __future__ import annotations

from packageurl import PackageURL
from purl2meta import get_metadata as _get_raw_metadata
from purl2meta import get_metadata_url, metadata_router  # noqa: F401 — re-exported

from ._compat import from_shorthand
from ._resolve import resolve_digest, resolve_download_url
from ._unify import unify_metadata

PURL_TYPE_TO_ECOSYSTEM = {
    "pypi": "python",
    "npm": "node",
    "cargo": "rust",
    "golang": "go",
    "oci": "container",
    "docker": "container",
    "github": None,
    "gitlab": None,
    "bitbucket": None,
}


def parse(purl: str) -> PackageURL:
    """Parse a purl string. Delegates to packageurl-python."""
    return PackageURL.from_string(purl)


def build(type: str, name: str, version: str | None = None, *,
          namespace: str | None = None, qualifiers: dict | None = None) -> str:
    """Build a purl string. Delegates to packageurl-python."""
    return PackageURL(type=type, namespace=namespace, name=name,
                      version=version, qualifiers=qualifiers).to_string()


def get_metadata(purl: str) -> dict | str | None:
    """Fetch raw metadata from the registry. Delegates to purl2meta."""
    return _get_raw_metadata(purl)


def get_unified_metadata(purl: str) -> dict:
    """Fetch metadata and map to standard schema: {description, license, url, name, version}."""
    raw = _get_raw_metadata(purl)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return {}
    return unify_metadata(purl, raw)


def resolve(purl: str) -> str | None:
    """Resolve a purl to a download URL."""
    return resolve_download_url(purl)


def detect_ecosystem(purl: str) -> str | None:
    """Map a purl type to an atrun ecosystem name."""
    p = PackageURL.from_string(purl)
    return PURL_TYPE_TO_ECOSYSTEM.get(p.type)


def resolve_url(url: str) -> str:
    """Resolve a URL to a downloadable form.

    If the URL is a purl (pkg:…) or shorthand (pypi:…, npm:…), resolve it
    to an HTTP/OCI download URL. HTTP/HTTPS/OCI URLs pass through unchanged.
    Raises SystemExit if a purl cannot be resolved.
    """
    purl_str: str | None = None
    if url.startswith("pkg:"):
        purl_str = url
    else:
        try:
            purl_str = from_shorthand(url)
        except ValueError:
            pass
    if purl_str is not None:
        resolved = resolve_download_url(purl_str)
        if resolved is None:
            raise SystemExit(f"Cannot resolve download URL for {purl_str}")
        return resolved
    return url


__all__ = [
    "parse",
    "build",
    "get_metadata",
    "get_unified_metadata",
    "resolve",
    "resolve_digest",
    "resolve_url",
    "detect_ecosystem",
    "from_shorthand",
    "get_metadata_url",
    "metadata_router",
]
