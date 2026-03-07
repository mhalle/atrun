"""Build and publish AT Protocol records for package distribution.

Handles lockfile parsing, distribution artifact hashing and verification,
metadata extraction, and record creation via XRPC.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .auth import load_session, refresh_session
from .ecosystems import detect_ecosystem_from_lockfile, detect_ecosystem_from_url, get_ecosystem

COLLECTION = "dev.atrun.module"


def _hash_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _name_version_from_dist_filename(filename: str) -> tuple[str, str]:
    """Extract (package_name, version) from a distribution filename.

    Supports wheel (.whl), sdist (.tar.gz), and npm tarball (.tgz) naming.
    For example:
      - 'atrun-0.5.0-py3-none-any.whl' -> ('atrun', '0.5.0')
      - 'cowsay-1.6.0.tgz' -> ('cowsay', '1.6.0')
    """
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
    """Resolve a distribution artifact to (name, version, sha256_hex).

    Handles three cases:
      - Both file and URL: hashes the local file and verifies it matches
        the remote download. Errors on mismatch. Silently uses the local
        hash if the remote is not yet available (e.g. GitHub release not
        uploaded).
      - URL only: downloads the artifact and hashes it. Ensures the URL
        is live before publishing.
      - Neither: returns None.
    """
    if dist_file and dist_url:
        name, version = _name_version_from_dist_filename(dist_file.name)
        local_sha256 = _hash_file(dist_file)
        try:
            resp = httpx.get(dist_url, follow_redirects=True)
            resp.raise_for_status()
            remote_sha256 = _hash_bytes(resp.content)
            if local_sha256 != remote_sha256:
                raise SystemExit(
                    f"Hash mismatch: local {dist_file.name} ({local_sha256[:12]}...) "
                    f"does not match remote ({remote_sha256[:12]}...)"
                )
        except httpx.HTTPError:
            pass  # Remote not available yet — use local hash
        return name, version, local_sha256
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
    """Build a dev.atrun.module record without publishing it.

    Args:
        lockfile: Lockfile content as a string. If None, auto-exports
            using the ecosystem's default tool (e.g. uv export for Python).
            Skipped entirely when strip_deps is True and a dist artifact
            is provided.
        dist_file: Path to a local distribution file to hash and include.
        dist_url: Public URL for the distribution. Becomes the download
            URL in the record.
        ecosystem: Target ecosystem ('python', 'node', 'deno'). Auto-detected
            from lockfile content or dist URL if None.
        permissions: Deno permissions list (e.g. ['read', 'env', 'net']).
            Only used for the deno ecosystem.
        strip_deps: If True, remove dependency arrays from resolved entries
            and skip lockfile parsing when a dist artifact is provided.

    Returns:
        A dict representing the complete AT Protocol record, ready for
        publishing or JSON serialization.
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
    post: bool = False,
) -> str:
    """Build and publish a record to AT Protocol.

    Builds the record via build_record(), then creates it on the
    authenticated user's AT Protocol repo using XRPC createRecord.

    If post is True, also creates a Bluesky post with a link card
    embedding the record's XRPC URL, using the record's metadata
    (package name, version, description) for the card content.

    Returns the AT URI of the created record
    (e.g. at://did:plc:abc123/dev.atrun.module/3mgxyz).
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

    record_uri = resp["uri"]

    if post:
        post_resp = _create_post(session, did, record_uri, record)
        if post_resp.get("error") in ("ExpiredToken", "InvalidToken"):
            session = refresh_session(session)
            post_resp = _create_post(session, did, record_uri, record)

    return record_uri


def _create_record(session: dict, did: str, record: dict) -> dict:
    """Send a createRecord XRPC request and return the response."""
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


def _create_post(session: dict, did: str, record_uri: str, record: dict) -> dict:
    """Create a Bluesky post with a link card pointing to the atrun record.

    The post text includes the package name and version. The link card
    embed uses the XRPC getRecord URL so the record is accessible via
    HTTPS.
    """
    package = record.get("package", "unknown")
    version = record.get("version", "")
    description = record.get("description", "")

    # Build XRPC URL from at:// URI
    parts = record_uri.replace("at://", "").split("/")
    xrpc_url = (
        f"https://bsky.social/xrpc/com.atproto.repo.getRecord"
        f"?repo={parts[0]}&collection={parts[1]}&rkey={parts[2]}"
    )

    text = f"{package} {version}"

    post = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "embed": {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": xrpc_url,
                "title": f"{package} {version}",
                "description": description,
            },
        },
    }

    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": post,
        },
    )
    return resp.json()
