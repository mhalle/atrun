"""Publish a uv.lock as an AT Protocol record."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .auth import load_session, refresh_session
from .lockfile import parse_uv_lock

COLLECTION = "dev.atrun.module"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _wheel_metadata(wheel_path: Path) -> tuple[str, str]:
    """Extract package name and version from a wheel filename."""
    # Wheel filenames follow: {name}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    stem = wheel_path.stem
    parts = stem.split("-")
    if len(parts) < 3:
        raise SystemExit(f"Cannot parse wheel filename: {wheel_path.name}")
    return parts[0], parts[1]


def build_record(
    lock_path: Path,
    python_version: str | None = None,
    platform: str | None = None,
    wheel_path: Path | None = None,
    wheel_url: str | None = None,
) -> dict:
    """Build the AT Protocol record from a lockfile without publishing it."""
    entries = parse_uv_lock(lock_path)
    if not entries:
        raise SystemExit("No resolved packages found in lockfile.")

    package_name = None
    if wheel_path and wheel_url:
        name, version = _wheel_metadata(wheel_path)
        package_name = name
        sha256 = _hash_file(wheel_path)
        entries.append({
            "packageName": name,
            "packageVersion": version,
            "sha256": sha256,
            "url": wheel_url,
        })
        entries.sort(key=lambda e: e["packageName"])

    record: dict = {
        "$type": COLLECTION,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "resolved": entries,
    }
    if package_name:
        record["package"] = package_name
    if python_version:
        record["pythonVersion"] = python_version
    if platform:
        record["platform"] = platform
    return record


def publish(
    lock_path: Path,
    python_version: str | None = None,
    platform: str | None = None,
    wheel_path: Path | None = None,
    wheel_url: str | None = None,
) -> str:
    """Publish the lockfile as an AT Protocol record.

    Returns the AT URI of the created record.
    """
    record = build_record(lock_path, python_version, platform, wheel_path, wheel_url)

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
