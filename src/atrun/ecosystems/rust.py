"""Rust (Cargo) ecosystem support."""

from __future__ import annotations

import tomllib

import httpx

LOCKFILE_EXTENSIONS = [".lock"]

CRATES_IO_DL = "https://crates.io/api/v1/crates"


def _crate_download_url(name: str, version: str) -> str:
    """Build the crates.io download URL for a crate."""
    return f"{CRATES_IO_DL}/{name}/{version}/download"


def parse_lockfile(content: str) -> list[dict]:
    """Parse a Cargo.lock and return sorted dependency entries.

    Extracts packages with source = "registry+https://github.com/rust-lang/crates.io-index"
    and a checksum field.
    """
    data = tomllib.loads(content)

    # Build name -> version map for resolving bare-name dependencies
    pkg_versions: dict[str, list[str]] = {}
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if name and version:
            pkg_versions.setdefault(name, []).append(version)

    entries = []
    seen = set()
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        source = pkg.get("source", "")
        checksum = pkg.get("checksum", "")

        if not checksum or "crates.io-index" not in source:
            continue

        dedup_key = (name, version)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        entry: dict = {
            "name": name,
            "version": version,
            "digest": f"sha256:{checksum}",
            "url": _crate_download_url(name, version),
            "artifactType": "crate",
        }

        deps = pkg.get("dependencies", [])
        if deps:
            dep_list = []
            for dep in deps:
                parts = dep.split()
                if len(parts) >= 2:
                    # Explicit "name version"
                    dep_list.append(f"{parts[0]}@{parts[1]}")
                else:
                    # Bare name — resolve to version
                    dep_versions = pkg_versions.get(dep, [])
                    if len(dep_versions) == 1:
                        dep_list.append(f"{dep}@{dep_versions[0]}")
                    elif dep_versions:
                        dep_list.append(f"{dep}@{dep_versions[0]}")
            if dep_list:
                entry["dependencies"] = sorted(dep_list)

        entries.append(entry)

    entries.sort(key=lambda e: e["name"])
    return entries


def export_lockfile() -> str:
    """Read ./Cargo.lock and return its content."""
    from pathlib import Path

    lock_path = Path("Cargo.lock")
    if not lock_path.exists():
        raise SystemExit("Cargo.lock not found in current directory.")
    return lock_path.read_text()


def build_metadata() -> dict:
    """Return ecosystem-specific metadata for the manifest."""
    return {}


def generate_requirements(artifacts: list[dict]) -> str:
    """Format artifacts as crate specs."""
    lines = []
    for entry in artifacts:
        lines.append(f"{entry['name']}@{entry['version']}")
    return "\n".join(lines)


def format_resolve_output(artifacts: list[dict]) -> str:
    """Format artifacts for output."""
    return generate_requirements(artifacts)


def generate_install_args(record: dict) -> list[str]:
    """Build cargo install command args."""
    package = record.get("package")
    artifacts = record.get("artifacts", [])
    pkg_entry = next((e for e in artifacts if e["name"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in artifacts list.")
    version = pkg_entry["version"]
    return ["cargo", "install", f"{package}@{version}"]


def generate_run_args(record: dict) -> list[str]:
    """Build args for running a Rust binary via cargo."""
    package = record.get("package")
    return ["cargo", "install", "--locked", package]


def fetch_metadata(url: str) -> dict:
    """Fetch metadata from crates.io API for a crate."""
    # Extract name and version from download URL
    # URL format: https://crates.io/api/v1/crates/{name}/{version}/download
    parts = url.rstrip("/download").rsplit("/", 2)
    if len(parts) < 3:
        raise ValueError(f"Cannot parse crate URL: {url}")
    # parts = [..., name, version]  or [..., "crates", name, version]
    # URL: .../crates/{name}/{version}/download
    url_path = url.replace(CRATES_IO_DL + "/", "")
    segments = url_path.split("/")
    name = segments[0]
    version = segments[1] if len(segments) > 1 else ""

    resp = httpx.get(
        f"{CRATES_IO_DL}/{name}/{version}",
        headers={"User-Agent": "atrun"},
    )
    resp.raise_for_status()
    data = resp.json()
    v = data.get("version", {})

    result: dict[str, str | list[str]] = {}
    if v.get("crate"):
        result["Name"] = v["crate"]
    if v.get("num"):
        result["Version"] = v["num"]
    if v.get("description"):
        result["Description"] = v["description"].strip()
    if v.get("license"):
        result["License"] = v["license"]
    if v.get("homepage"):
        result["Homepage"] = v["homepage"]
    if v.get("repository"):
        result["Repository"] = v["repository"]
    if v.get("downloads"):
        result["Downloads"] = str(v["downloads"])

    return result


def extract_dist_metadata(url: str) -> dict:
    """Extract standardized metadata from a crates.io URL."""
    meta = fetch_metadata(url)
    result: dict[str, str] = {}
    if "Description" in meta:
        result["description"] = str(meta["Description"])
    if "License" in meta:
        result["license"] = str(meta["License"])
    if "Repository" in meta:
        result["url"] = str(meta["Repository"])
    elif "Homepage" in meta:
        result["url"] = str(meta["Homepage"])
    return result
