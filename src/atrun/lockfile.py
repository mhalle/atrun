"""Parse uv.lock files into resolved dependency entries."""

from __future__ import annotations

import tomllib
from pathlib import Path


def parse_uv_lock(lock_path: Path) -> list[dict]:
    """Parse a uv.lock file and return sorted dependency entries.

    Each entry has: packageName, packageVersion, sha256, url.
    """
    text = lock_path.read_text()
    data = tomllib.loads(text)

    entries = []
    for pkg in data.get("package", []):
        name = pkg.get("name")
        version = pkg.get("version")
        if not name or not version:
            continue

        # Wheels are under [[package.wheels]]
        for wheel in pkg.get("wheels", []):
            url = wheel.get("url")
            hash_str = wheel.get("hash")
            if not url or not hash_str:
                continue

            # uv.lock stores hashes as "sha256:<hex>"
            if hash_str.startswith("sha256:"):
                sha256 = hash_str[len("sha256:"):]
            else:
                continue

            entries.append({
                "packageName": name,
                "packageVersion": version,
                "sha256": sha256,
                "url": url,
            })
            break  # one wheel per package is sufficient

        # Also check sdists if no wheel was found
        if not any(e["packageName"] == name for e in entries):
            for sdist in pkg.get("sdists", []):
                url = sdist.get("url")
                hash_str = sdist.get("hash")
                if not url or not hash_str:
                    continue
                if hash_str.startswith("sha256:"):
                    sha256 = hash_str[len("sha256:"):]
                else:
                    continue
                entries.append({
                    "packageName": name,
                    "packageVersion": version,
                    "sha256": sha256,
                    "url": url,
                })
                break

    # Sort alphabetically by package name for deterministic serialization
    entries.sort(key=lambda e: e["packageName"])
    return entries
