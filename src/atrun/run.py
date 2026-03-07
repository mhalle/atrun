"""Fetch, inspect, and run atrun modules from AT Protocol records.

Handles AT URI resolution, XRPC record fetching, TID timestamp decoding,
and ecosystem-dispatched execution.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import httpx

AT_URI_RE = re.compile(r"^at://([^/]+)/([^/]+)/([^/]+)$")
BSKY_POST_RE = re.compile(r"^https://bsky\.app/profile/([^/]+)/post/([^/]+)$")


def resolve_pds_url(handle_or_did: str) -> tuple[str, str]:
    """Resolve a handle or DID to a (PDS base URL, DID) tuple.

    If given a handle (e.g. alice.bsky.social), resolves it to a DID first.
    Currently assumes bsky.social as the PDS for all users.
    """
    if handle_or_did.startswith("did:"):
        did = handle_or_did
    else:
        resp = httpx.get(
            "https://bsky.social/xrpc/com.atproto.identity.resolveHandle",
            params={"handle": handle_or_did},
        )
        resp.raise_for_status()
        did = resp.json()["did"]

    return "https://bsky.social", did


def _decode_tid_timestamp(tid: str) -> str | None:
    """Decode an AT Protocol TID (Timestamp ID) to an ISO 8601 string.

    TIDs are base32-sortable encoded 64-bit values where the upper 53 bits
    represent microseconds since the Unix epoch.

    Returns None if the TID cannot be decoded.
    """
    from datetime import datetime, timezone

    charset = "234567abcdefghijklmnopqrstuvwxyz"
    try:
        n = 0
        for c in tid:
            n = n * 32 + charset.index(c)
        us = n >> 10
        dt = datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (ValueError, OSError):
        return None


def _resolve_handle(did: str) -> str | None:
    """Resolve a DID to its current handle via the Bluesky API.

    Returns the handle string, or None if resolution fails.
    """
    try:
        resp = httpx.get(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
            params={"actor": did},
        )
        if resp.status_code == 200:
            return resp.json().get("handle")
    except Exception:
        pass
    return None


def _fetch_from_bsky_post(handle: str, rkey: str) -> dict:
    """Fetch an atrun record embedded in a Bluesky post.

    Resolves the post, then looks for a dev.atrun.module reference in:
      1. embed.external.uri (link card pointing to XRPC getRecord URL)
      2. embed.record.uri (direct record embed)
      3. facets with link features pointing to XRPC getRecord URLs

    Follows the found URI to fetch the actual atrun record.
    """
    pds_url, did = resolve_pds_url(handle)
    resp = httpx.get(
        f"{pds_url}/xrpc/com.atproto.repo.getRecord",
        params={"repo": did, "collection": "app.bsky.feed.post", "rkey": rkey},
    )
    resp.raise_for_status()
    post = resp.json()["value"]

    # Look for atrun record URI in embed or facets
    record_url = None
    embed = post.get("embed", {})
    embed_type = embed.get("$type", "")

    if embed_type == "app.bsky.embed.external":
        uri = embed.get("external", {}).get("uri", "")
        if "dev.atrun.module" in uri:
            record_url = uri
    elif embed_type == "app.bsky.embed.record":
        uri = embed.get("record", {}).get("uri", "")
        if "dev.atrun.module" in uri:
            record_url = uri

    if not record_url:
        # Check facets for links containing atrun record references
        for facet in post.get("facets", []):
            for feature in facet.get("features", []):
                uri = feature.get("uri", "")
                if "dev.atrun.module" in uri:
                    record_url = uri
                    break
            if record_url:
                break

    if not record_url:
        raise SystemExit("Post does not contain a dev.atrun.module record reference.")

    # Follow the URI — could be an at:// URI or an XRPC HTTPS URL
    return fetch_record(record_url)


def fetch_record(uri: str, unsigned: bool = False) -> dict:
    """Fetch a record and return a dict with 'at' and 'content' keys.

    Accepts three kinds of URIs:
      - AT URI (at://did/collection/rkey): resolved via XRPC getRecord
      - XRPC HTTPS URL: fetched directly, envelope extracted from response
      - Plain HTTPS URL (requires unsigned=True): raw JSON, no AT envelope

    The 'at' key contains envelope info when available:
      - uri: the AT URI of the record
      - cid: content identifier (hash of the record)
      - did: the publisher's decentralized identifier
      - handle: the publisher's human-readable handle
      - timestamp: creation time decoded from the TID

    The 'content' key contains the record value (the dev.atrun.module data).

    For unsigned HTTPS URLs, 'at' is None.
    """
    if uri.startswith("https://"):
        # Check for bsky.app post URL — extract embedded atrun record
        bsky_m = BSKY_POST_RE.match(uri)
        if bsky_m:
            return _fetch_from_bsky_post(bsky_m.group(1), bsky_m.group(2))

        resp = httpx.get(uri)
        resp.raise_for_status()
        data = resp.json()

        # XRPC response has uri/cid/value wrapper
        if "value" in data and "cid" in data:
            at_info = {"uri": data["uri"], "cid": data["cid"]}
            m = AT_URI_RE.match(data.get("uri", ""))
            if m:
                did = m.group(1)
                rkey = m.group(3)
                at_info["did"] = did
                handle = _resolve_handle(did)
                if handle:
                    at_info["handle"] = handle
                ts = _decode_tid_timestamp(rkey)
                if ts:
                    at_info["timestamp"] = ts
            return {"at": at_info, "content": data["value"]}

        if not unsigned:
            raise SystemExit("URL does not return an AT Protocol record. Use --unsigned for plain HTTPS.")
        return {"at": None, "content": data}

    m = AT_URI_RE.match(uri)
    if not m:
        raise SystemExit(f"Invalid AT URI: {uri}")

    authority, collection, rkey = m.groups()
    pds_url, did = resolve_pds_url(authority)

    resp = httpx.get(
        f"{pds_url}/xrpc/com.atproto.repo.getRecord",
        params={"repo": did, "collection": collection, "rkey": rkey},
    )
    resp.raise_for_status()
    data = resp.json()

    at_info = {"uri": data["uri"], "cid": data["cid"], "did": did}
    handle = _resolve_handle(did)
    if handle:
        at_info["handle"] = handle
    ts = _decode_tid_timestamp(rkey)
    if ts:
        at_info["timestamp"] = ts

    return {"at": at_info, "content": data["value"]}


def generate_requirements(resolved: list[dict], record: dict | None = None) -> str:
    """Generate dependency output in the ecosystem's native format.

    If a record is provided, detects the ecosystem and uses its format.
    Otherwise falls back to Python requirements.txt with hash pins.
    """
    if record is not None:
        from .ecosystems import detect_ecosystem_from_record, get_ecosystem
        eco_name = detect_ecosystem_from_record(record)
        eco_mod = get_ecosystem(eco_name)
        return eco_mod.format_resolve_output(resolved)

    # Legacy fallback: Python requirements.txt format
    lines = []
    for entry in resolved:
        name = entry["packageName"]
        url = entry["url"]
        hash_str = entry.get("hash", entry.get("sha256", ""))
        if ":" not in hash_str:
            hash_str = f"sha256:{hash_str}"
        lines.append(f"{name} @ {url} --hash={hash_str}")
    return "\n".join(lines)


def run_module(uri: str, unsigned: bool = False) -> None:
    """Fetch a record and run the package in a temporary environment.

    For Python, creates an isolated venv, installs dependencies with hash
    verification, and executes the package.

    For Node/Deno, delegates to the ecosystem's native run command.
    """
    from .ecosystems import detect_ecosystem_from_record, get_ecosystem

    record = fetch_record(uri, unsigned=unsigned)["content"]
    resolved = record.get("resolved", [])
    if not resolved:
        raise SystemExit("Record has no resolved packages.")

    package = record.get("package")
    if not package:
        raise SystemExit("Record has no 'package' field — cannot determine what to run.")

    eco_name = detect_ecosystem_from_record(record)
    eco_mod = get_ecosystem(eco_name)

    if eco_name == "python":
        requirements = eco_mod.generate_requirements(resolved)

        with tempfile.TemporaryDirectory(prefix="atrun-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            req_file = tmpdir_path / "requirements.txt"
            req_file.write_text(requirements)

            venv_path = tmpdir_path / ".venv"

            subprocess.run(
                ["uv", "venv", str(venv_path)],
                check=True,
            )

            subprocess.run(
                [
                    "uv", "pip", "install",
                    "--require-hashes",
                    "--python", str(venv_path / "bin" / "python"),
                    "-r", str(req_file),
                ],
                check=True,
            )

            subprocess.run(
                [
                    "uv", "run",
                    "--python", str(venv_path / "bin" / "python"),
                    package,
                ],
                check=True,
            )
    else:
        cmd = eco_mod.generate_run_args(record)
        subprocess.run(cmd, check=True)
