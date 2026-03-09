"""Build and publish AT Protocol records for package distribution.

Handles lockfile parsing, distribution artifact hashing and verification,
metadata extraction, and record creation via XRPC.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from .auth import load_session, refresh_session
from .ecosystems import PACKAGE_TYPES, detect_ecosystem_from_lockfile, detect_ecosystem_from_url, get_ecosystem
from .verify import hash_bytes as _hash_bytes

COLLECTION = "dev.atpub.manifest"


def _list_all_records_client(session: dict, repo: str, collection: str, **extra_params: object) -> list[dict]:
    """Page through all listRecords results via an authenticated XRPC call.

    Returns the full list of record dicts (each with uri, cid, value keys).
    """
    records: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"repo": repo, "collection": collection, "limit": 100, **extra_params}
        if cursor:
            params["cursor"] = cursor
        resp = httpx.get(
            "https://bsky.social/xrpc/com.atproto.repo.listRecords",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            params=params,
        )
        if resp.status_code != 200:
            break
        data = resp.json()
        records.extend(data.get("records", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return records


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
    # Wheels use underscores in name (PEP 427), so simple split works.
    # For sdists/tarballs, find the version boundary: first part that starts
    # with a digit or 'v' followed by a digit (e.g. v1.2.3).
    if not filename.endswith(".whl"):
        for i in range(1, len(parts)):
            p = parts[i]
            if p and (p[0].isdigit() or (p[0] == "v" and len(p) > 1 and p[1].isdigit())):
                return "-".join(parts[:i]), "-".join(parts[i:])
    return parts[0], parts[1]


def _name_version_from_dist_url(url: str) -> tuple[str, str]:
    """Extract (name, version) from a distribution URL.

    Handles crates.io URLs (/.../crates/{name}/{version}/download)
    and falls back to filename-based parsing.
    """
    # oci:// URL: oci://registry/name:tag
    if url.startswith("oci://"):
        ref = url.removeprefix("oci://")
        # Split tag from the end
        last_colon = ref.rfind(":")
        if last_colon > ref.rfind("/"):
            return ref[:last_colon], ref[last_colon + 1:]
        return ref, "latest"
    # crates.io: /api/v1/crates/{name}/{version}/download
    if "crates.io" in url and "/download" in url:
        m = re.search(r"/crates/([^/]+)/([^/]+)/download", url)
        if m:
            return m.group(1), m.group(2)
    # proxy.golang.org: /{module}/@v/{version}.zip
    if "proxy.golang.org" in url:
        m = re.search(r"proxy\.golang\.org/(.+)/@v/(.+)\.zip", url)
        if m:
            # Unescape module path (!x -> X)
            module = re.sub(r"!([a-z])", lambda m: m.group(1).upper(), m.group(1))
            return module, m.group(2)
    # npm scoped packages: registry.npmjs.org/@scope/pkg/-/pkg-version.tgz
    if "registry.npmjs.org" in url and "/@" in url:
        m = re.search(r"registry\.npmjs\.org/(@[^/]+/[^/]+)/-/", url)
        if m:
            scoped_name = m.group(1)
            filename = url.rsplit("/", 1)[-1]
            _, version = _name_version_from_dist_filename(filename)
            return scoped_name, version
    filename = url.rsplit("/", 1)[-1]
    return _name_version_from_dist_filename(filename)


def build_record(
    lockfile: str | None = None,
    dist_urls: tuple[str, ...] = (),
    ecosystem: str | None = None,
    strip_deps: bool = False,
    derived_from: tuple[str, ...] | None = None,
    description: str | None = None,
    license: str | None = None,
    url: str | None = None,
) -> dict:
    """Build a dev.atpub.manifest record without publishing it.

    Args:
        lockfile: Lockfile content as a string. If None, auto-exports
            using the ecosystem's default tool (e.g. uv export for Python).
            Skipped entirely when strip_deps is True and a dist URL is provided.
        dist_urls: Public URLs, package URLs (pkg:pypi/name@ver), or shorthands
            for the distribution. All resolved URLs go into the artifact's urls array.
        ecosystem: Target ecosystem ('python', 'node', 'rust'). Auto-detected
            from lockfile content or dist URL if None.
        strip_deps: If True, remove dependency arrays from resolved entries
            and skip lockfile parsing when a dist artifact is provided.
        derived_from: URIs of records this derives from. Accepts AT URIs,
            XRPC HTTPS URLs, or bsky.app post URLs. Each resolved to a strongRef.
        description: Package description (overrides extracted metadata).
        license: SPDX license identifier (overrides extracted metadata).
        url: Package homepage URL (overrides extracted metadata).

    Returns:
        A dict representing the complete AT Protocol record, ready for
        publishing or JSON serialization.
    """
    from . import purl as _purl

    # Resolve each dist_url: identify purls, resolve download URLs internally.
    # artifact_urls: what goes into the record (purls kept as-is)
    # download_urls: resolved HTTP URLs for hashing/downloading
    artifact_urls: list[str] = []
    download_urls: list[str] = []
    purl_strs: list[str] = []
    for du in dist_urls:
        purl_str: str | None = None
        if du.startswith("pkg:"):
            purl_str = du
        else:
            try:
                purl_str = _purl.from_shorthand(du)
            except ValueError:
                pass  # raw URL
        if purl_str is not None:
            purl_strs.append(purl_str)
            resolved = _purl.resolve(purl_str)
            if resolved is None:
                raise SystemExit(f"Cannot resolve distribution URL for {purl_str}")
            artifact_urls.append(purl_str)
            download_urls.append(resolved)
        else:
            artifact_urls.append(du)
            download_urls.append(du)

    first_purl = purl_strs[0] if purl_strs else None
    first_download_url = download_urls[0] if download_urls else None

    # Get name/version: from first purl (authoritative), fallback to URL parsing
    package_name: str | None = None
    package_version: str | None = None
    if first_purl:
        p = _purl.parse(first_purl)
        if p.type == "npm" and p.namespace:
            package_name = f"{p.namespace}/{p.name}"
        elif p.type == "golang" and p.namespace:
            package_name = f"{p.namespace}/{p.name}"
        else:
            package_name = p.name
        package_version = p.version
    elif first_download_url:
        package_name, package_version = _name_version_from_dist_url(first_download_url)

    # Determine ecosystem
    if ecosystem is None and first_purl is not None:
        ecosystem = _purl.detect_ecosystem(first_purl)
    if ecosystem is None and lockfile is not None:
        ecosystem = detect_ecosystem_from_lockfile(lockfile)
    if ecosystem is None and first_download_url:
        ecosystem = detect_ecosystem_from_url(first_download_url) or "python"
    if ecosystem is None:
        ecosystem = "python"

    eco_mod = get_ecosystem(ecosystem)

    # Resolve digest: try API-based extraction first, download as fallback
    digest: str | None = None
    for ps in purl_strs:
        digest = _purl.resolve_digest(ps)
        if digest:
            break
    if digest is None and first_download_url:
        if first_download_url.startswith("oci://"):
            from .ecosystems.container import _resolve_digest
            ref = first_download_url.removeprefix("oci://")
            oci_digest = _resolve_digest(ref)
            digest = oci_digest  # already algo:hex format
        else:
            resp = httpx.get(first_download_url, follow_redirects=True)
            resp.raise_for_status()
            sha256 = _hash_bytes(resp.content)
            digest = f"sha256:{sha256}"

    has_dist = bool(artifact_urls) and digest is not None

    # Parse lockfile if available; skip if strip_deps and we have a dist artifact
    entries: list[dict] = []
    if strip_deps and has_dist and lockfile is None:
        pass  # No lockfile needed
    else:
        lockfile_str = lockfile if lockfile is not None else eco_mod.export_lockfile()
        entries = eco_mod.parse_lockfile(lockfile_str)
        if not entries and not has_dist:
            raise SystemExit("No resolved packages found.")

    if has_dist and package_name and package_version:
        existing = next(
            (e for e in entries if e["name"] == package_name and e["version"] == package_version),
            None,
        )
        if existing is None:
            entries.append({
                "name": package_name,
                "version": package_version,
                "digest": digest,
                "urls": artifact_urls,
            })
            entries.sort(key=lambda e: e["name"])
        else:
            # Update existing entry with resolved URLs
            existing["urls"] = artifact_urls
            if digest:
                existing["digest"] = digest

    if strip_deps:
        entries = [{k: v for k, v in e.items() if k != "dependencies"} for e in entries]

    # Extract metadata: purl-based first (no download), then ecosystem fallback
    dist_meta: dict[str, str] = {}
    for ps in purl_strs:
        try:
            purl_meta = _purl.get_unified_metadata(ps)
            for field in ("description", "license", "url"):
                if field not in dist_meta and field in purl_meta:
                    dist_meta[field] = purl_meta[field]
        except Exception:
            pass
    # Ecosystem metadata fallback for missing fields
    if first_download_url and any(f not in dist_meta for f in ("description", "license", "url")):
        try:
            eco_meta = eco_mod.extract_dist_metadata(first_download_url)
            for field in ("description", "license", "url"):
                if field not in dist_meta and field in eco_meta:
                    dist_meta[field] = eco_meta[field]
        except Exception:
            pass

    # CLI flags override everything
    if description is not None:
        dist_meta["description"] = description
    if license is not None:
        dist_meta["license"] = license
    if url is not None:
        dist_meta["url"] = url

    record: dict = {
        "$type": COLLECTION,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifacts": entries,
    }
    if package_name:
        record["package"] = package_name
        pkg_entry = next((e for e in entries if e["name"] == package_name), None)
        if pkg_entry:
            record["version"] = pkg_entry["version"]
            record["root"] = entries.index(pkg_entry)
    for field in ("description", "license", "url"):
        if field in dist_meta:
            record[field] = dist_meta[field]

    # packageType from ecosystem
    package_type = PACKAGE_TYPES.get(ecosystem)
    if package_type:
        record["packageType"] = package_type

    # tool identifier
    from importlib.metadata import version as pkg_version
    try:
        record["tool"] = f"atrun@{pkg_version('atrun')}"
    except Exception:
        record["tool"] = "atrun"

    # Ecosystem-specific metadata
    if hasattr(eco_mod, "build_metadata"):
        meta = eco_mod.build_metadata()
        if meta:
            record["metadata"] = meta

    if derived_from:
        from .run import fetch_record
        refs = []
        for uri in derived_from:
            result = fetch_record(uri)
            at_info = result.get("at")
            if at_info and "uri" in at_info and "cid" in at_info:
                refs.append({"uri": at_info["uri"], "cid": at_info["cid"]})
            else:
                raise SystemExit(f"Cannot resolve derivedFrom: {uri} (no AT envelope)")
        record["derivedFrom"] = refs

    return record


def publish(
    lockfile: str | None = None,
    dist_urls: tuple[str, ...] = (),
    ecosystem: str | None = None,
    strip_deps: bool = False,
    derived_from: tuple[str, ...] | None = None,
    no_derived_from: bool = False,
    post: bool = False,
    handle: str | None = None,
    force: bool = False,
    description: str | None = None,
    license: str | None = None,
    url: str | None = None,
) -> tuple[str, str | None]:
    """Build and publish a record to AT Protocol.

    Builds the record via build_record(), then creates it on the
    authenticated user's AT Protocol repo using XRPC createRecord.

    If post is True, also creates a Bluesky post with a link card
    embedding the record's XRPC URL, using the record's metadata
    (package name, version, description) for the card content.

    Returns (record_uri, post_uri) where post_uri is None if --post
    was not used.
    """
    record = build_record(lockfile, dist_urls=dist_urls, ecosystem=ecosystem, strip_deps=strip_deps, derived_from=derived_from, description=description, license=license, url=url)

    session = load_session(handle=handle)
    did = session["did"]

    # Check for duplicate publish
    package = record.get("package")
    version = record.get("version")
    if package and version and not force:
        existing = _find_duplicate_record(session, did, package, version, record.get("packageType"))
        if existing:
            raise SystemExit(
                f"{package}@{version} is already published: {existing}\n"
                f"Use --force to publish again."
            )
    if package and "derivedFrom" not in record and not no_derived_from:
        prev = _find_previous_record(session, did, package, record.get("packageType"))
        if prev:
            record["derivedFrom"] = [prev]

    resp = _create_record(session, did, record)
    if resp.get("error") in ("ExpiredToken", "InvalidToken"):
        session = refresh_session(session, handle=handle)
        resp = _create_record(session, did, record)

    if "uri" not in resp:
        raise SystemExit(f"Failed to create record: {resp}")

    record_uri = resp["uri"]

    post_uri = None
    if post:
        post_resp = _create_post(session, did, record_uri, record)
        if post_resp.get("error") in ("ExpiredToken", "InvalidToken"):
            session = refresh_session(session, handle=handle)
            post_resp = _create_post(session, did, record_uri, record)
        post_uri = post_resp.get("uri")

    return record_uri, post_uri


def _find_duplicate_record(session: dict, did: str, package: str, version: str, package_type: str | None = None) -> str | None:
    """Check if an identical package+version record already exists.

    Returns the AT URI of the existing record if found, None otherwise.
    """
    all_records = _list_all_records_client(session, did, COLLECTION, reverse=False)
    for rec in all_records:
        value = rec.get("value", {})
        if value.get("package") != package:
            continue
        if value.get("version") != version:
            continue
        if package_type and value.get("packageType") != package_type:
            continue
        return rec["uri"]
    return None


def _find_previous_record(session: dict, did: str, package: str, package_type: str | None = None) -> dict | None:
    """Find the most recent existing record for the same package.

    Lists records in reverse chronological order (newest TID first) and
    returns the first one matching the package name and packageType as a
    strongRef {uri, cid}, or None if no previous record exists.
    """
    all_records = _list_all_records_client(session, did, COLLECTION, reverse=False)
    for rec in all_records:
        value = rec.get("value", {})
        if value.get("package") != package:
            continue
        if package_type and value.get("packageType") != package_type:
            continue
        return {"uri": rec["uri"], "cid": rec["cid"]}
    return None


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

    url = record.get("url", "")

    # Build post text: "package version\ndescription\nurl" clipped to 300 graphemes
    text = f"{package} {version}"
    if description:
        text += f"\n{description}"
    if url:
        text += f"\n{url}"
    if len(text) > 300:
        text = text[:299] + "…"

    # Build facets for any URL in the text
    facets = []
    if url and url in text:
        byte_start = text.encode("utf-8").index(url.encode("utf-8"))
        byte_end = byte_start + len(url.encode("utf-8"))
        facets.append({
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        })

    post = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **({"facets": facets} if facets else {}),
        "embed": {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": xrpc_url,
                "title": f"{package} {version}",
                "description": f"{description}\n{url}" if url else description,
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
