"""Publish a uv.lock as an AT Protocol record."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from .auth import load_session, refresh_session
from .lockfile import parse_uv_lock

COLLECTION = "dev.atrun.module"


def build_record(lock_path: Path, python_version: str | None = None, platform: str | None = None) -> dict:
    """Build the AT Protocol record from a lockfile without publishing it."""
    entries = parse_uv_lock(lock_path)
    if not entries:
        raise SystemExit("No resolved packages found in lockfile.")

    record: dict = {
        "$type": COLLECTION,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "resolved": entries,
    }
    if python_version:
        record["pythonVersion"] = python_version
    if platform:
        record["platform"] = platform
    return record


def publish(lock_path: Path, python_version: str | None = None, platform: str | None = None) -> str:
    """Publish the lockfile as an AT Protocol record.

    Returns the AT URI of the created record.
    """
    record = build_record(lock_path, python_version, platform)

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
