"""Fetch, inspect, and run atrun modules from AT Protocol records.

Handles AT URI resolution, XRPC record fetching, TID timestamp decoding,
and ecosystem-dispatched execution.
"""

from __future__ import annotations

import re

import httpx

AT_URI_RE = re.compile(r"^at://([^/]+)/([^/]+)/([^/]+)$")
BSKY_POST_RE = re.compile(r"^https://bsky\.app/profile/([^/]+)/post/([^/]+)$")
# @handle:package or @handle:package@version (version can be "latest")
SHORTHAND_RE = re.compile(r"^@([^:]+):([^@]+)(?:@(.+))?$")

YANK_COLLECTION = "dev.atpub.yank"


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

    Resolves the post, then looks for a dev.atpub.manifest reference in:
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
        if "dev.atpub.manifest" in uri:
            record_url = uri
    elif embed_type == "app.bsky.embed.record":
        uri = embed.get("record", {}).get("uri", "")
        if "dev.atpub.manifest" in uri:
            record_url = uri

    if not record_url:
        # Check facets for links containing atrun record references
        for facet in post.get("facets", []):
            for feature in facet.get("features", []):
                uri = feature.get("uri", "")
                if "dev.atpub.manifest" in uri:
                    record_url = uri
                    break
            if record_url:
                break

    if not record_url:
        raise SystemExit("Post does not contain a dev.atpub.manifest record reference.")

    # Follow the URI — could be an at:// URI or an XRPC HTTPS URL
    return fetch_record(record_url)


def list_records(handle: str, package: str | None = None) -> list[dict]:
    """List dev.atpub.manifest records for a user.

    Returns a list of dicts with uri, package, version, ecosystem, and
    timestamp fields. If package is specified, filters to that package only.
    Records are returned newest first.
    """
    pds_url, did = resolve_pds_url(handle)

    resp = httpx.get(
        f"{pds_url}/xrpc/com.atproto.repo.listRecords",
        params={"repo": did, "collection": "dev.atpub.manifest", "limit": 100, "reverse": False},
    )
    resp.raise_for_status()

    results = []
    for rec in resp.json().get("records", []):
        value = rec.get("value", {})
        pkg = value.get("package", "")
        if package and pkg != package:
            continue

        # Extract rkey for timestamp
        m = AT_URI_RE.match(rec.get("uri", ""))
        ts = None
        if m:
            ts = _decode_tid_timestamp(m.group(3))

        from .ecosystems import detect_ecosystem_from_artifacts
        eco_name = detect_ecosystem_from_artifacts(value.get("artifacts", []), record=value)

        entry = {
            "uri": rec["uri"],
            "package": pkg,
            "version": value.get("version", ""),
            "ecosystem": eco_name,
            "timestamp": ts,
        }
        if "packageType" in value:
            entry["packageType"] = value["packageType"]
        results.append(entry)

    return results


def fetch_yanks(handle_or_did: str) -> dict[str, str]:
    """Fetch all yank records for a user.

    Returns a dict mapping module record URI -> yank reason.
    """
    pds_url, did = resolve_pds_url(handle_or_did)

    resp = httpx.get(
        f"{pds_url}/xrpc/com.atproto.repo.listRecords",
        params={"repo": did, "collection": YANK_COLLECTION, "limit": 100},
    )
    if resp.status_code != 200:
        return {}

    yanks: dict[str, str] = {}
    for rec in resp.json().get("records", []):
        value = rec.get("value", {})
        subject = value.get("subject", {})
        uri = subject.get("uri", "")
        if uri:
            yanks[uri] = value.get("reason", "")
    return yanks


def _resolve_shorthand(handle: str, package: str, version: str | None) -> dict:
    """Resolve @handle:package[@version] to a record.

    Lists the user's dev.atpub.manifest records and finds the one matching
    the package name. If version is None or 'latest', returns the most
    recent non-yanked version. Otherwise matches the exact version
    (even if yanked).
    """
    pds_url, did = resolve_pds_url(handle)

    resp = httpx.get(
        f"{pds_url}/xrpc/com.atproto.repo.listRecords",
        params={"repo": did, "collection": "dev.atpub.manifest", "limit": 100, "reverse": False},
    )
    resp.raise_for_status()

    # For latest resolution, skip yanked versions
    is_latest = not version or version == "latest"
    yanks = fetch_yanks(handle) if is_latest else {}

    for rec in resp.json().get("records", []):
        value = rec.get("value", {})
        if value.get("package") != package:
            continue
        if not is_latest:
            if value.get("version") != version:
                continue
        elif rec["uri"] in yanks:
            continue  # skip yanked versions when resolving latest
        # Match found — fetch via fetch_record for full envelope
        return fetch_record(rec["uri"])

    if version and version != "latest":
        raise SystemExit(f"No record found for {package}@{version} by @{handle}")
    raise SystemExit(f"No record found for {package} by @{handle}")


def fetch_record(uri: str, unsigned: bool = False) -> dict:
    """Fetch a record and return a dict with 'at' and 'content' keys.

    Accepts four kinds of URIs:
      - Shorthand (@handle:package[@version]): resolved via listRecords
      - AT URI (at://did/collection/rkey): resolved via XRPC getRecord
      - XRPC HTTPS URL: fetched directly, envelope extracted from response
      - Plain HTTPS URL (requires unsigned=True): raw JSON, no AT envelope

    The 'at' key contains envelope info when available:
      - uri: the AT URI of the record
      - cid: content identifier (hash of the record)
      - did: the publisher's decentralized identifier
      - handle: the publisher's human-readable handle
      - timestamp: creation time decoded from the TID

    The 'content' key contains the record value (the dev.atpub.manifest data).

    For unsigned HTTPS URLs, 'at' is None.
    """
    # Check for @handle:package[@version] shorthand
    shorthand_m = SHORTHAND_RE.match(uri)
    if shorthand_m:
        return _resolve_shorthand(shorthand_m.group(1), shorthand_m.group(2), shorthand_m.group(3))

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


def fetch_social_info(at_info: dict) -> dict | None:
    """Fetch social context for a published record.

    Looks up the publisher's profile and searches their recent posts for
    one embedding the record's XRPC URL. If found, fetches like count,
    repost count, and reply thread.

    Returns a dict with 'publisher' and optionally 'post' sections,
    or None if at_info is missing.
    """
    if not at_info or "did" not in at_info:
        return None

    did = at_info["did"]
    record_uri = at_info.get("uri", "")

    result: dict = {}

    # Publisher profile
    try:
        resp = httpx.get(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
            params={"actor": did},
        )
        if resp.status_code == 200:
            profile = resp.json()
            result["publisher"] = {
                "handle": profile.get("handle", ""),
                "displayName": profile.get("displayName", ""),
                "followersCount": profile.get("followersCount", 0),
                "followsCount": profile.get("followsCount", 0),
                "postsCount": profile.get("postsCount", 0),
            }
            desc = profile.get("description", "")
            if desc:
                result["publisher"]["description"] = desc
    except Exception:
        pass

    # Build XRPC URL to match against post embeds
    m = AT_URI_RE.match(record_uri)
    if not m:
        return result or None

    xrpc_url = (
        f"https://bsky.social/xrpc/com.atproto.repo.getRecord"
        f"?repo={m.group(1)}&collection={m.group(2)}&rkey={m.group(3)}"
    )

    # Search publisher's recent posts for one embedding this record
    try:
        resp = httpx.get(
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
            params={"actor": did, "limit": 50, "filter": "posts_no_replies"},
        )
        if resp.status_code != 200:
            return result or None

        post_uri = None
        for item in resp.json().get("feed", []):
            post = item.get("post", {})
            embed = post.get("record", {}).get("embed", {})
            external_uri = embed.get("external", {}).get("uri", "")
            if xrpc_url in external_uri:
                post_uri = post.get("uri")
                break
            # Also check facets
            for facet in post.get("record", {}).get("facets", []):
                for feature in facet.get("features", []):
                    if xrpc_url in feature.get("uri", ""):
                        post_uri = post.get("uri")
                        break

        if not post_uri:
            return result or None

        # Fetch post thread for engagement
        resp = httpx.get(
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread",
            params={"uri": post_uri, "depth": 10},
        )
        if resp.status_code != 200:
            return result or None

        thread = resp.json().get("thread", {})
        post_data = thread.get("post", {})

        post_info: dict = {
            "uri": post_uri,
            "likeCount": post_data.get("likeCount", 0),
            "repostCount": post_data.get("repostCount", 0),
            "replyCount": post_data.get("replyCount", 0),
        }

        # Extract replies
        replies = []
        for reply in thread.get("replies", []):
            reply_post = reply.get("post", {})
            author = reply_post.get("author", {})
            text = reply_post.get("record", {}).get("text", "")
            if text:
                replies.append({
                    "handle": author.get("handle", ""),
                    "text": text,
                })
        if replies:
            post_info["replies"] = replies

        result["post"] = post_info

    except Exception:
        pass

    return result or None


def generate_requirements(artifacts: list[dict], record: dict | None = None) -> str:
    """Generate dependency output in the ecosystem's native format.

    If a record is provided, detects the ecosystem and uses its format.
    Otherwise falls back to Python requirements.txt with hash pins.
    """
    if record is not None:
        from .ecosystems import detect_ecosystem_from_artifacts, get_ecosystem
        eco_name = detect_ecosystem_from_artifacts(record.get("artifacts", []), record=record)
        eco_mod = get_ecosystem(eco_name)
        return eco_mod.format_resolve_output(artifacts)

    # Legacy fallback: Python requirements.txt format
    lines = []
    for entry in artifacts:
        name = entry["name"]
        url = entry["url"]
        hash_str = entry.get("digest", entry.get("sha256", ""))
        if ":" not in hash_str:
            hash_str = f"sha256:{hash_str}"
        lines.append(f"{name} @ {url} --hash={hash_str}")
    return "\n".join(lines)


def run_module(uri: str, unsigned: bool = False, engine: str | None = None, do_verify: bool = True) -> None:
    """Fetch a record and run the package in a temporary environment.

    For Python, downloads and verifies the main artifact hash, then
    runs via uvx with the verified local file.

    For Node, delegates to the ecosystem's native run command.
    The engine parameter selects the Node.js package manager (pnpm, bun, npm).
    """
    import sys

    from .ecosystems import detect_ecosystem_from_artifacts, get_ecosystem

    record = fetch_record(uri, unsigned=unsigned)["content"]
    artifacts = record.get("artifacts", [])
    if not artifacts:
        raise SystemExit("Record has no resolved packages.")

    package = record.get("package")
    if not package:
        # For multi-image container records, suggest using docker compose directly
        eco_name = detect_ecosystem_from_artifacts(artifacts, record=record)
        if eco_name == "container":
            raise SystemExit(
                "Multi-image container record has no main package. "
                "Use 'atrun fetch' to pull the images, then run with docker compose."
            )
        raise SystemExit("Record has no 'package' field — cannot determine what to run.")

    eco_name = detect_ecosystem_from_artifacts(artifacts, record=record)
    eco_mod = get_ecosystem(eco_name)

    import os

    if eco_name == "container":
        from .ecosystems.container import _build_image_ref, verify_digest as _verify_container

        pkg_entry = next((e for e in artifacts if e["name"] == package), artifacts[0])
        pkg_hash = pkg_entry.get("digest", "")

        if do_verify and pkg_hash:
            ref = f"{pkg_entry['name']}:{pkg_entry['version']}"
            print(f"Verifying {package}...", file=sys.stderr)
            try:
                _verify_container(ref, pkg_hash, engine or "docker")
            except SystemExit as exc:
                raise SystemExit(str(exc))
            print("Digest verified.", file=sys.stderr)

        digest_ref = _build_image_ref(pkg_entry)
        selected_engine = engine or "docker"
        cmd = [selected_engine, "run", "--rm", digest_ref]
        os.execvp(cmd[0], cmd)

    if eco_name == "python":
        pkg_entry = next((e for e in artifacts if e["name"] == package), None)
        if not pkg_entry:
            raise SystemExit(f"Package '{package}' not found in artifacts list.")

        pkg_url = pkg_entry["url"]
        pkg_hash = pkg_entry.get("digest", "")

        if do_verify and pkg_hash:
            from .verify import HashMismatchError, download_and_verify

            print(f"Verifying {package}...", file=sys.stderr)
            try:
                verified_path = download_and_verify(pkg_url, pkg_hash)
            except HashMismatchError as exc:
                raise SystemExit(str(exc))
            pkg_url = f"file://{verified_path}"
            print("Hash verified.", file=sys.stderr)
        elif do_verify and not pkg_hash:
            print(f"Warning: no hash in record for {package}, skipping verification.", file=sys.stderr)

        cmd = ["uvx", "--from", f"{package} @ {pkg_url}", package]
        os.execvp(cmd[0], cmd)
    elif eco_name == "node":
        pkg_entry = next((e for e in artifacts if e["name"] == package), None)
        if not pkg_entry:
            raise SystemExit(f"Package '{package}' not found in artifacts list.")

        pkg_hash = pkg_entry.get("digest", "")
        verified_path = None

        if do_verify and pkg_hash:
            from .verify import HashMismatchError, download_and_verify

            print(f"Verifying {package}...", file=sys.stderr)
            try:
                verified_path = download_and_verify(pkg_entry["url"], pkg_hash)
            except HashMismatchError as exc:
                raise SystemExit(str(exc))
            print("Hash verified.", file=sys.stderr)
            pkg_spec = f"file://{verified_path}"
        elif do_verify and not pkg_hash:
            print(f"Warning: no hash in record for {package}, skipping verification.", file=sys.stderr)
            pkg_spec = pkg_entry["url"]
        else:
            pkg_spec = pkg_entry["url"]

        selected_engine = engine or "pnpm"
        if selected_engine == "bun":
            cmd = ["bunx", pkg_spec]
        elif selected_engine == "npm":
            cmd = ["npx", pkg_spec]
        else:
            cmd = ["pnpx", pkg_spec]
        os.execvp(cmd[0], cmd)
    elif eco_name == "rust":
        pkg_entry = next((e for e in artifacts if e["name"] == package), None)
        if do_verify and pkg_entry:
            pkg_hash = pkg_entry.get("digest", "")
            if pkg_hash:
                from .verify import HashMismatchError, verify_artifact

                print(f"Verifying {package}...", file=sys.stderr)
                try:
                    verify_artifact(pkg_entry["url"], pkg_hash)
                except HashMismatchError as exc:
                    raise SystemExit(str(exc))
                print("Hash verified.", file=sys.stderr)
            else:
                print(f"Warning: no hash in record for {package}, skipping verification.", file=sys.stderr)

        cmd = eco_mod.generate_run_args(record)
        os.execvp(cmd[0], cmd)
    else:
        cmd = eco_mod.generate_run_args(record)
        if eco_name == "go":
            os.environ["GO111MODULE"] = "on"
        os.execvp(cmd[0], cmd)
