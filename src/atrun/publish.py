"""Publish resolved dependencies as an AT Protocol record."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .auth import load_session, refresh_session
from .lockfile import export_pylock, parse_pylock

def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

COLLECTION = "dev.atrun.module"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _name_version_from_dist_filename(filename: str) -> tuple[str, str]:
    """Extract package name and version from a distribution filename.

    Supports wheel (.whl) and sdist (.tar.gz) naming conventions.
    """
    # Strip extension
    if filename.endswith(".whl"):
        stem = filename[:-4]
    elif filename.endswith(".tar.gz"):
        stem = filename[:-7]
    elif "." in filename:
        stem = filename.rsplit(".", 1)[0]
    else:
        stem = filename
    parts = stem.split("-")
    if len(parts) < 2:
        raise SystemExit(f"Cannot parse distribution filename: {filename}")
    return parts[0], parts[1]


def _resolve_dist(dist_file: Path | None, dist_url: str | None) -> tuple[str, str, str] | None:
    """Resolve distribution to (name, version, sha256) from local file or URL."""
    if dist_file and dist_url:
        name, version = _name_version_from_dist_filename(dist_file.name)
        sha256 = _hash_file(dist_file)
        return name, version, sha256
    if dist_url and not dist_file:
        filename = dist_url.rsplit("/", 1)[-1]
        name, version = _name_version_from_dist_filename(filename)
        resp = httpx.get(dist_url, follow_redirects=True)
        resp.raise_for_status()
        sha256 = _hash_bytes(resp.content)
        return name, version, sha256
    return None


def build_record(
    lockfile: str | None = None,
    dist_file: Path | None = None,
    dist_url: str | None = None,
) -> dict:
    """Build the AT Protocol record without publishing it.

    lockfile: pylock.toml content as string. If None, runs uv export.
    """
    pylock_str = lockfile if lockfile is not None else export_pylock()
    entries = parse_pylock(pylock_str)
    if not entries:
        raise SystemExit("No resolved packages found.")

    package_name = None
    dist_info = _resolve_dist(dist_file, dist_url)
    if dist_info:
        name, version, sha256 = dist_info
        package_name = name
        entries.append({
            "packageName": name,
            "packageVersion": version,
            "sha256": sha256,
            "url": dist_url,
        })
        entries.sort(key=lambda e: e["packageName"])

    record: dict = {
        "$type": COLLECTION,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ecosystem": {
            "$type": "dev.atrun.module#pythonEcosystem",
        },
        "resolved": entries,
    }
    if package_name:
        record["package"] = package_name
    return record


def publish(
    lockfile: str | None = None,
    dist_file: Path | None = None,
    dist_url: str | None = None,
) -> str:
    """Publish the lockfile as an AT Protocol record.

    Returns the AT URI of the created record.
    """
    record = build_record(lockfile, dist_file, dist_url)

    session = load_session()
    did = session["did"]

    try:
        at_uri = _create_record(session, did, record)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            session = refresh_session(session)
            at_uri = _create_record(session, did, record)
        else:
            raise

    return at_uri


def _create_record(session: dict, did: str, record: dict) -> str:
    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={
            "repo": did,
            "collection": COLLECTION,
            "record": record,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["uri"]
