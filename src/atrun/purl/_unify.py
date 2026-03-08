"""Map raw registry metadata to a unified schema."""

from __future__ import annotations

from packageurl import PackageURL


def unify_metadata(purl: str, raw: dict) -> dict:
    """Map raw registry metadata to {name, version, description, license, url}.

    Returns a dict with only the fields that could be extracted.
    """
    p = PackageURL.from_string(purl)
    mapper = _MAPPERS.get(p.type, _default_mapper)
    return mapper(p, raw)


def _map_pypi(p: PackageURL, raw: dict) -> dict:
    info = raw.get("info", {})
    result: dict = {}
    if info.get("name"):
        result["name"] = info["name"]
    if info.get("version"):
        result["version"] = info["version"]
    if info.get("summary"):
        result["description"] = info["summary"]
    license_val = info.get("license_expression") or info.get("license")
    if license_val:
        result["license"] = license_val
    url = info.get("home_page")
    if not url:
        url = (info.get("project_urls") or {}).get("Homepage")
    if url:
        result["url"] = url
    return result


def _map_npm(p: PackageURL, raw: dict) -> dict:
    result: dict = {}
    if raw.get("name"):
        result["name"] = raw["name"]
    if raw.get("version"):
        result["version"] = raw["version"]
    if raw.get("description"):
        result["description"] = raw["description"]
    if raw.get("license"):
        result["license"] = raw["license"]
    url = raw.get("homepage")
    if not url:
        repo = raw.get("repository")
        if isinstance(repo, dict):
            url = repo.get("url")
        elif isinstance(repo, str):
            url = repo
    if url:
        result["url"] = url
    return result


def _map_cargo(p: PackageURL, raw: dict) -> dict:
    # crates.io versioned endpoint wraps data in "version" key
    v = raw.get("version", raw)
    crate = raw.get("crate", {})
    result: dict = {}
    if v.get("crate") or crate.get("name"):
        result["name"] = v.get("crate") or crate.get("name")
    if v.get("num"):
        result["version"] = v["num"]
    if v.get("description") or crate.get("description"):
        result["description"] = v.get("description") or crate.get("description")
    if v.get("license"):
        result["license"] = v["license"]
    url = v.get("repository") or v.get("homepage") or crate.get("repository") or crate.get("homepage")
    if url:
        result["url"] = url
    return result


def _map_golang(p: PackageURL, raw: dict) -> dict:
    module = f"{p.namespace}/{p.name}" if p.namespace else p.name
    result: dict = {"url": f"https://pkg.go.dev/{module}"}
    if p.name:
        result["name"] = module
    if raw.get("Version"):
        result["version"] = raw["Version"]
    return result


def _map_github(p: PackageURL, raw: dict) -> dict:
    result: dict = {}
    repo_name = f"{p.namespace}/{p.name}" if p.namespace else p.name
    result["name"] = repo_name
    if raw.get("tag_name"):
        result["version"] = raw["tag_name"]
    if raw.get("body"):
        result["description"] = raw["body"]
    license_info = raw.get("license")
    if isinstance(license_info, dict) and license_info.get("spdx_id"):
        result["license"] = license_info["spdx_id"]
    url = raw.get("homepage") or raw.get("html_url")
    if url:
        result["url"] = url
    return result


def _default_mapper(p: PackageURL, raw: dict) -> dict:
    """Best-effort mapper for unknown registry types."""
    result: dict = {}
    for key in ("name", "version", "description", "license"):
        if raw.get(key):
            result[key] = raw[key]
    url = raw.get("homepage") or raw.get("url") or raw.get("html_url")
    if url:
        result["url"] = url
    return result


_MAPPERS = {
    "pypi": _map_pypi,
    "npm": _map_npm,
    "cargo": _map_cargo,
    "golang": _map_golang,
    "github": _map_github,
}
