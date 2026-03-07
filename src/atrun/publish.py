"""Publish resolved dependencies as an AT Protocol record."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .auth import load_session, refresh_session
from .ecosystems import detect_ecosystem_from_lockfile, detect_ecosystem_from_url, get_ecosystem

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
    ecosystem: str | None = None,
    permissions: list[str] | None = None,
    strip_deps: bool = False,
) -> dict:
    """Build the AT Protocol record without publishing it.

    lockfile: lockfile content as string. If None, uses ecosystem's export.
    ecosystem: "python", "node", or "deno". Auto-detected if None.
    permissions: Deno permissions list (only used for deno ecosystem).
    strip_deps: If True, remove dependency info from entries.
    """
    # Determine ecosystem
    if ecosystem is None and lockfile is not None:
        ecosystem = detect_ecosystem_from_lockfile(lockfile)
    elif ecosystem is None and dist_url:
        ecosystem = detect_ecosystem_from_url(dist_url) or "python"
    elif ecosystem is None:
        ecosystem = "python"

    eco_mod = get_ecosystem(ecosystem)

    # Parse lockfile if available; skip if strip_deps and we have a dist artifact
    entries = []
    dist_info = _resolve_dist(dist_file, dist_url)

    if strip_deps and dist_info and lockfile is None:
        # No lockfile needed — just the dist artifact
        pass
    else:
        lockfile_str = lockfile if lockfile is not None else eco_mod.export_lockfile()
        entries = eco_mod.parse_lockfile(lockfile_str)
        if not entries and not dist_info:
            raise SystemExit("No resolved packages found.")

    package_name = None
    if dist_info:
        name, version, sha256 = dist_info
        package_name = name
        # Only add if not already present in lockfile entries
        existing = next((e for e in entries if e["packageName"] == name and e["packageVersion"] == version), None)
        if existing is None:
            entries.append({
                "packageName": name,
                "packageVersion": version,
                "hash": f"sha256:{sha256}",
                "url": dist_url,
            })
            entries.sort(key=lambda e: e["packageName"])

    if strip_deps:
        entries = [{k: v for k, v in e.items() if k != "dependencies"} for e in entries]

    # Extract metadata from the dist artifact (prefer local file)
    dist_meta: dict[str, str] = {}
    if dist_info:
        try:
            if dist_file and hasattr(eco_mod, "extract_local_dist_metadata"):
                dist_meta = eco_mod.extract_local_dist_metadata(dist_file)
            elif dist_url:
                dist_meta = eco_mod.extract_dist_metadata(dist_url)
        except Exception:
            pass  # metadata extraction is best-effort

    record: dict = {
        "$type": COLLECTION,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ecosystem": eco_mod.build_ecosystem_value(permissions=permissions) if ecosystem == "deno" else eco_mod.build_ecosystem_value(),
        "resolved": entries,
    }
    if package_name:
        record["package"] = package_name
        # Add version from the resolved entry
        pkg_entry = next((e for e in entries if e["packageName"] == package_name), None)
        if pkg_entry:
            record["version"] = pkg_entry["packageVersion"]
    for field in ("description", "license", "url"):
        if field in dist_meta:
            record[field] = dist_meta[field]
    return record


def publish(
    lockfile: str | None = None,
    dist_file: Path | None = None,
    dist_url: str | None = None,
    ecosystem: str | None = None,
    permissions: list[str] | None = None,
    strip_deps: bool = False,
) -> str:
    """Publish the lockfile as an AT Protocol record.

    Returns the AT URI of the created record.
    """
    record = build_record(lockfile, dist_file, dist_url, ecosystem=ecosystem, permissions=permissions, strip_deps=strip_deps)

    session = load_session()
    did = session["did"]

    resp = _create_record(session, did, record)
    if resp.get("error") in ("ExpiredToken", "InvalidToken"):
        session = refresh_session(session)
        resp = _create_record(session, did, record)

    if "uri" not in resp:
        raise SystemExit(f"Failed to create record: {resp}")

    return resp["uri"]


def _create_record(session: dict, did: str, record: dict) -> dict:
    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={
            "repo": did,
            "collection": COLLECTION,
            "record": record,
        },
    )
    return resp.json()
