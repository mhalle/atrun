"""Build and publish AT Protocol records for package distribution.

Handles lockfile parsing, distribution artifact hashing and verification,
metadata extraction, and record creation via XRPC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from .auth import load_session, refresh_session
from .ecosystems import PACKAGE_TYPES, detect_ecosystem_from_lockfile, detect_ecosystem_from_url, get_ecosystem
from .verify import hash_bytes as _hash_bytes, hash_file as _hash_file

COLLECTION = "dev.atpub.manifest"


def _resolve_npm_shorthand(spec: str) -> str:
    """Resolve npm:package or npm:package@version to a tarball URL.

    Without @version, fetches the latest version from the npm registry.
    """
    name = spec.removeprefix("npm:")
    if "@" in name and not name.startswith("@"):
        name, version = name.rsplit("@", 1)
    elif name.startswith("@") and "@" in name.split("/", 1)[-1]:
        # Scoped package: @scope/pkg@version
        scope_pkg, version = name.rsplit("@", 1)
        name = scope_pkg
    else:
        version = None

    resp = httpx.get(f"https://registry.npmjs.org/{name}")
    resp.raise_for_status()
    data = resp.json()

    if version is None:
        version = data.get("dist-tags", {}).get("latest")
        if not version:
            raise SystemExit(f"Cannot determine latest version of {name}")

    tarball = data.get("versions", {}).get(version, {}).get("dist", {}).get("tarball")
    if not tarball:
        raise SystemExit(f"Cannot find tarball for {name}@{version}")
    return tarball


def _resolve_crate_shorthand(spec: str) -> str:
    """Resolve crate:name or crate:name@version to a crates.io download URL.

    Without @version, fetches the latest version from crates.io.
    """
    name = spec.removeprefix("crate:")
    if "@" in name:
        name, version = name.rsplit("@", 1)
    else:
        version = None

    resp = httpx.get(
        f"https://crates.io/api/v1/crates/{name}",
        headers={"User-Agent": "atrun"},
    )
    resp.raise_for_status()
    data = resp.json()

    if version is None:
        version = data.get("crate", {}).get("max_version")
        if not version:
            raise SystemExit(f"Cannot determine latest version of crate {name}")

    return f"https://crates.io/api/v1/crates/{name}/{version}/download"


def _resolve_go_shorthand(spec: str) -> str:
    """Resolve go:module or go:module@version to a proxy.golang.org URL.

    Without @version, fetches the latest version from the Go module proxy.
    """
    import re

    module = spec.removeprefix("go:")
    if "@" in module:
        module, version = module.rsplit("@", 1)
    else:
        version = None

    # Escape uppercase letters for proxy URL
    escaped = re.sub(r"[A-Z]", lambda m: f"!{m.group().lower()}", module)

    if version is None:
        resp = httpx.get(f"https://proxy.golang.org/{escaped}/@latest")
        resp.raise_for_status()
        data = resp.json()
        version = data.get("Version")
        if not version:
            raise SystemExit(f"Cannot determine latest version of {module}")

    return f"https://proxy.golang.org/{escaped}/@v/{version}.zip"


def _resolve_github_shorthand(spec: str) -> str:
    """Resolve gh:owner/repo or gh:owner/repo@tag to a release asset URL.

    Without @tag, uses the latest release. With @tag, fetches that specific
    release. Picks the first asset matching common dist extensions
    (.whl, .tgz, .tar.gz). Errors if no suitable asset is found.
    """
    repo = spec.removeprefix("gh:")
    if "@" in repo:
        repo, tag = repo.rsplit("@", 1)
        api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    else:
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    resp = httpx.get(api_url)
    resp.raise_for_status()
    data = resp.json()

    dist_extensions = (".whl", ".tgz", ".tar.gz")
    for asset in data.get("assets", []):
        name = asset["name"]
        if any(name.endswith(ext) for ext in dist_extensions):
            return asset["browser_download_url"]

    # Fall back to first asset if no dist extension matched
    assets = data.get("assets", [])
    if assets:
        return assets[0]["browser_download_url"]

    raise SystemExit(f"No assets found in latest release of {repo}")



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


def _name_version_from_dist_url(url: str) -> tuple[str, str]:
    """Extract (name, version) from a distribution URL.

    Handles crates.io URLs (/.../crates/{name}/{version}/download)
    and falls back to filename-based parsing.
    """
    # crates.io: /api/v1/crates/{name}/{version}/download
    if "crates.io" in url and "/download" in url:
        import re
        m = re.search(r"/crates/([^/]+)/([^/]+)/download", url)
        if m:
            return m.group(1), m.group(2)
    # proxy.golang.org: /{module}/@v/{version}.zip
    if "proxy.golang.org" in url:
        import re
        m = re.search(r"proxy\.golang\.org/(.+)/@v/(.+)\.zip", url)
        if m:
            # Unescape module path (!x -> X)
            module = re.sub(r"!([a-z])", lambda m: m.group(1).upper(), m.group(1))
            return module, m.group(2)
    filename = url.rsplit("/", 1)[-1]
    return _name_version_from_dist_filename(filename)


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
        name, version = _name_version_from_dist_url(dist_url)
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
    strip_deps: bool = False,
    derived_from: str | None = None,
) -> dict:
    """Build a dev.atpub.manifest record without publishing it.

    Args:
        lockfile: Lockfile content as a string. If None, auto-exports
            using the ecosystem's default tool (e.g. uv export for Python).
            Skipped entirely when strip_deps is True and a dist artifact
            is provided.
        dist_file: Path to a local distribution file to hash and include.
        dist_url: Public URL for the distribution. Becomes the download
            URL in the record.
        ecosystem: Target ecosystem ('python', 'node', 'rust'). Auto-detected
            from lockfile content or dist URL if None.
        strip_deps: If True, remove dependency arrays from resolved entries
            and skip lockfile parsing when a dist artifact is provided.
        derived_from: URI of the record this derives from. Accepts AT URIs,
            XRPC HTTPS URLs, or bsky.app post URLs. Resolved to a strongRef.

    Returns:
        A dict representing the complete AT Protocol record, ready for
        publishing or JSON serialization.
    """
    # Resolve dist URL shorthands
    if dist_url and dist_url.startswith("gh:"):
        dist_url = _resolve_github_shorthand(dist_url)
    elif dist_url and dist_url.startswith("npm:"):
        dist_url = _resolve_npm_shorthand(dist_url)
    elif dist_url and dist_url.startswith("crate:"):
        dist_url = _resolve_crate_shorthand(dist_url)
    elif dist_url and dist_url.startswith("go:"):
        dist_url = _resolve_go_shorthand(dist_url)

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
        existing = next((e for e in entries if e["name"] == name and e["version"] == version), None)
        if existing is None:
            entries.append({
                "name": name,
                "version": version,
                "hash": f"sha256:{sha256}",
                "url": dist_url,
            })
            entries.sort(key=lambda e: e["name"])

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
        "resolved": entries,
    }
    if package_name:
        record["package"] = package_name
        pkg_entry = next((e for e in entries if e["name"] == package_name), None)
        if pkg_entry:
            record["version"] = pkg_entry["version"]
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
        result = fetch_record(derived_from)
        at_info = result.get("at")
        if at_info and "uri" in at_info and "cid" in at_info:
            record["derivedFrom"] = [{"uri": at_info["uri"], "cid": at_info["cid"]}]
        else:
            raise SystemExit(f"Cannot resolve derivedFrom: {derived_from} (no AT envelope)")

    return record


def publish(
    lockfile: str | None = None,
    dist_file: Path | None = None,
    dist_url: str | None = None,
    ecosystem: str | None = None,
    strip_deps: bool = False,
    derived_from: str | None = None,
    no_derived_from: bool = False,
    post: bool = False,
) -> str:
    """Build and publish a record to AT Protocol.

    Builds the record via build_record(), then creates it on the
    authenticated user's AT Protocol repo using XRPC createRecord.

    If post is True, also creates a Bluesky post with a link card
    embedding the record's XRPC URL, using the record's metadata
    (package name, version, description) for the card content.

    Returns the AT URI of the created record
    (e.g. at://did:plc:abc123/dev.atpub.manifest/3mgxyz).
    """
    record = build_record(lockfile, dist_file, dist_url, ecosystem=ecosystem, strip_deps=strip_deps, derived_from=derived_from)

    session = load_session()
    did = session["did"]

    # Auto-link to previous version if not explicitly provided or suppressed
    package = record.get("package")
    if package and "derivedFrom" not in record and not no_derived_from:
        prev = _find_previous_record(session, did, package)
        if prev:
            record["derivedFrom"] = [prev]

    resp = _create_record(session, did, record)
    if resp.get("error") in ("ExpiredToken", "InvalidToken"):
        session = refresh_session(session)
        resp = _create_record(session, did, record)

    if "uri" not in resp:
        raise SystemExit(f"Failed to create record: {resp}")

    record_uri = resp["uri"]

    post_uri = None
    if post:
        post_resp = _create_post(session, did, record_uri, record)
        if post_resp.get("error") in ("ExpiredToken", "InvalidToken"):
            session = refresh_session(session)
            post_resp = _create_post(session, did, record_uri, record)
        post_uri = post_resp.get("uri")

    return record_uri, post_uri


def _find_previous_record(session: dict, did: str, package: str) -> dict | None:
    """Find the most recent existing record for the same package.

    Lists records in reverse chronological order (newest TID first) and
    returns the first one matching the package name as a strongRef
    {uri, cid}, or None if no previous record exists.
    """
    resp = httpx.get(
        "https://bsky.social/xrpc/com.atproto.repo.listRecords",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        params={"repo": did, "collection": COLLECTION, "limit": 100, "reverse": False},
    )
    if resp.status_code != 200:
        return None
    for rec in resp.json().get("records", []):
        if rec.get("value", {}).get("package") == package:
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
