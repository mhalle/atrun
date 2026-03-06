"""Parse pylock.toml into resolved dependency entries."""

from __future__ import annotations

import subprocess
import tomllib


def export_pylock() -> str:
    """Run uv export --format pylock.toml and return stdout."""
    result = subprocess.run(
        ["uv", "export", "--format", "pylock.toml", "--no-emit-project"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def parse_pylock(toml_str: str) -> list[dict]:
    """Parse a pylock.toml string and return sorted dependency entries.

    Each entry has: packageName, packageVersion, sha256, url.
    """
    data = tomllib.loads(toml_str)

    entries = []
    for pkg in data.get("packages", []):
        name = pkg.get("name")
        version = pkg.get("version")
        if not name or not version:
            continue

        # Prefer wheels over sdists
        wheels = pkg.get("wheels", [])
        if wheels:
            wheel = wheels[0]
            url = wheel.get("url")
            hashes = wheel.get("hashes", {})
            sha256 = hashes.get("sha256")
            if url and sha256:
                entries.append({
                    "packageName": name,
                    "packageVersion": version,
                    "sha256": sha256,
                    "url": url,
                })
                continue

        # Fall back to sdist
        sdist = pkg.get("sdist")
        if sdist:
            url = sdist.get("url")
            hashes = sdist.get("hashes", {})
            sha256 = hashes.get("sha256")
            if url and sha256:
                entries.append({
                    "packageName": name,
                    "packageVersion": version,
                    "sha256": sha256,
                    "url": url,
                })

    entries.sort(key=lambda e: e["packageName"])
    return entries
