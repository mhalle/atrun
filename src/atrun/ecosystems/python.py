"""Python ecosystem support (pylock.toml + wheels)."""

from __future__ import annotations

import subprocess
import tomllib

LOCKFILE_EXTENSIONS = [".toml"]


def _extract_hash(hashes: dict) -> str | None:
    for algo in ("sha256", "sha512"):
        if algo in hashes:
            return f"{algo}:{hashes[algo]}"
    return None


def parse_lockfile(content: str) -> list[dict]:
    """Parse a pylock.toml string and return sorted dependency entries."""
    data = tomllib.loads(content)

    entries = []
    for pkg in data.get("packages", []):
        name = pkg.get("name")
        version = pkg.get("version")
        if not name or not version:
            continue

        # Collect per-artifact metadata
        meta: dict[str, str] = {}
        requires_python = pkg.get("requires-python")
        if requires_python:
            meta["requires-python"] = str(requires_python)

        wheels = pkg.get("wheels", [])
        if wheels:
            wheel = wheels[0]
            url = wheel.get("url")
            hash_str = _extract_hash(wheel.get("hashes", {}))
            if url and hash_str:
                entry: dict = {
                    "name": name,
                    "version": version,
                    "digest": hash_str,
                    "url": url,
                    "artifactType": "wheel",
                }
                if meta:
                    entry["metadata"] = meta
                entries.append(entry)
                continue

        sdist = pkg.get("sdist")
        if sdist:
            url = sdist.get("url")
            hash_str = _extract_hash(sdist.get("hashes", {}))
            if url and hash_str:
                entry = {
                    "name": name,
                    "version": version,
                    "digest": hash_str,
                    "url": url,
                    "artifactType": "sdist",
                }
                if meta:
                    entry["metadata"] = meta
                entries.append(entry)

    entries.sort(key=lambda e: e["name"])
    return entries


def export_lockfile() -> str:
    """Run uv export --format pylock.toml and return stdout."""
    result = subprocess.run(
        ["uv", "export", "--format", "pylock.toml", "--no-emit-project"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def build_metadata() -> dict:
    """Return ecosystem-specific metadata for the manifest.

    Includes the Python version used for resolution.
    """
    import sys
    return {"pythonVersion": f"{sys.version_info.major}.{sys.version_info.minor}"}


def generate_requirements(artifacts: list[dict]) -> str:
    """Generate a requirements.txt with --hash pins from artifacts entries."""
    lines = []
    for entry in artifacts:
        name = entry["name"]
        url = entry["url"]
        hash_str = entry.get("digest", "")
        if ":" not in hash_str:
            hash_str = f"sha256:{hash_str}"
        lines.append(f"{name} @ {url} --hash={hash_str}")
    return "\n".join(lines)


def generate_install_args(record: dict) -> list[str]:
    """Build uv tool install command args."""
    package = record.get("package")
    artifacts = record.get("artifacts", [])
    pkg_entry = next((e for e in artifacts if e["name"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in artifacts list.")

    return [
        "uv", "tool", "install",
        f"{package} @ {pkg_entry['url']}",
    ]


def generate_run_args(record: dict) -> list[str]:
    """Build args for running a Python module."""
    package = record.get("package")
    return ["uv", "run", package]


def fetch_metadata(url: str) -> dict:
    """Fetch metadata from a wheel URL."""
    from ..wheel import fetch_wheel_metadata
    return fetch_wheel_metadata(url)


def _metadata_from_wheel_meta(meta: dict) -> dict[str, str]:
    """Convert wheel METADATA fields to standardized metadata."""
    result: dict[str, str] = {}
    if "Summary" in meta:
        result["description"] = str(meta["Summary"])
    if "License-Expression" in meta:
        result["license"] = str(meta["License-Expression"])
    elif "License" in meta:
        result["license"] = str(meta["License"])
    if "Home-page" in meta:
        result["url"] = str(meta["Home-page"])
    elif "Project-URL" in meta:
        urls = meta["Project-URL"]
        if isinstance(urls, list) and urls:
            _, _, url_val = urls[0].partition(", ")
            if url_val:
                result["url"] = url_val
    return result


def extract_dist_metadata(url: str) -> dict:
    """Extract standardized metadata from a wheel URL."""
    from ..wheel import fetch_wheel_metadata
    return _metadata_from_wheel_meta(fetch_wheel_metadata(url))


def extract_local_dist_metadata(path: "Path") -> dict:
    """Extract standardized metadata from a local wheel file."""
    import io
    import zipfile
    from email.parser import Parser

    with zipfile.ZipFile(path) as zf:
        metadata_path = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")),
            None,
        )
        if not metadata_path:
            return {}
        raw = zf.read(metadata_path).decode("utf-8")

    msg = Parser().parsestr(raw)
    meta: dict[str, str | list[str]] = {}
    for field in ("Summary", "License", "License-Expression", "Home-page"):
        value = msg.get(field)
        if value:
            meta[field] = value
    project_urls = msg.get_all("Project-URL")
    if project_urls:
        meta["Project-URL"] = project_urls
    return _metadata_from_wheel_meta(meta)


def format_resolve_output(artifacts: list[dict]) -> str:
    """Format artifacts for output (requirements.txt format)."""
    return generate_requirements(artifacts)
