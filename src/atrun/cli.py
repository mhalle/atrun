"""Command-line interface for atrun.

Provides commands for publishing, inspecting, installing, and running
packages distributed via AT Protocol records.
"""

import getpass
import json
import os
import sys
from pathlib import Path

import click
import httpx


@click.group()
@click.version_option(package_name="atrun")
def cli():
    """Social package distribution on AT Protocol.

    Publish, inspect, install, and run packages from AT Protocol records.
    Supports Python (pip/uv), Node.js (npm/pnpm/bun), Rust (cargo), and Go ecosystems.

    Records can be referenced by AT URI (at://did/collection/rkey) or by
    HTTPS URL (XRPC getRecord endpoint or plain JSON with --unsigned).
    """


@cli.command()
@click.option("--handle", prompt="Bluesky handle", help="Bluesky handle (e.g. alice.bsky.social). Leading @ is stripped.")
def login(handle: str):
    """Authenticate with Bluesky using an app password.

    Stores the session locally for subsequent publish operations.
    Create an app password at https://bsky.app/settings/app-passwords.
    """
    from .auth import login as do_login

    app_password = getpass.getpass("App password: ")
    session = do_login(handle, app_password)
    click.echo(f"Logged in as {session['handle']} ({session['did']})")


@cli.command()
@click.option("--lockfile", type=click.Path(), help="Path to lockfile, or '-' for stdin. Omit to auto-export via the ecosystem's default tool.")
@click.option("--dist-file", type=click.Path(exists=True, path_type=Path), help="Local distribution file (wheel, tarball) to hash and include.")
@click.option("--dist-url", help="Public URL where the distribution is hosted. Used as the download URL in the record. If --dist-file is also given, hashes are verified to match.")
@click.option("--ecosystem", "eco", type=click.Choice(["python", "node", "rust", "go", "container"]), default=None, help="Target ecosystem. Auto-detected from lockfile content or dist URL if omitted.")
@click.option("--deps", is_flag=True, help="Include the full dependency graph in the record, enabling frozen lockfile verification on install.")
@click.option("--derived-from", "derived_from", multiple=True, help="AT URI, XRPC URL, or bsky.app URL of a record this derives from. Can be specified multiple times. Auto-detected from previous versions if omitted.")
@click.option("--no-derived-from", is_flag=True, help="Suppress automatic derivedFrom linking to previous versions.")
@click.option("--post", is_flag=True, help="Create a Bluesky post with a link card embedding the published record.")
@click.option("--dry-run", is_flag=True, help="Print the record as JSON without publishing to AT Protocol.")
def publish(lockfile: str | None, dist_file: Path | None, dist_url: str | None, eco: str | None, deps: bool, derived_from: tuple[str, ...], no_derived_from: bool, post: bool, dry_run: bool):
    """Publish a package record to AT Protocol.

    Parses the lockfile, hashes the distribution artifact, extracts metadata
    (description, license, url) from the dist file, and creates a
    dev.atpub.manifest record on the authenticated user's AT Protocol repo.

    Without --lockfile, auto-exports using the ecosystem's default tool
    (uv export for Python). With --dist-url and no --deps, the lockfile
    can be omitted entirely.

    \b
    Examples:
      atrun publish --dist-url https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz
      atrun publish --lockfile pylock.toml --dist-file dist/pkg-1.0.whl --dist-url https://example.com/pkg-1.0.whl
      atrun publish --dist-url https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz --lockfile package-lock.json --deps
    """
    from .publish import build_record, publish as do_publish

    lockfile_str = None
    if lockfile == "-":
        lockfile_str = sys.stdin.read()
    elif lockfile:
        lockfile_str = Path(lockfile).read_text()

    if dry_run:
        record = build_record(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url, ecosystem=eco, strip_deps=not deps, derived_from=derived_from or None)
        click.echo(json.dumps(record, indent=2))
        return

    record_uri, post_uri = do_publish(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url, ecosystem=eco, strip_deps=not deps, derived_from=derived_from or None, no_derived_from=no_derived_from, post=post)
    click.echo(record_uri)
    if post_uri:
        # Convert at://did/app.bsky.feed.post/rkey to bsky.app URL
        from .run import _resolve_handle
        parts = post_uri.replace("at://", "").split("/")
        did = parts[0]
        handle = _resolve_handle(did) or did
        click.echo(f"https://bsky.app/profile/{handle}/post/{parts[2]}")


@cli.command(name="list")
@click.argument("target")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array.")
def list_cmd(target: str, as_json: bool):
    """List packages or versions published by a user.

    TARGET is either @handle (list all packages) or @handle:package
    (list all versions of a package).

    \b
    Examples:
      atrun list @alice.bsky.social
      atrun list @alice.bsky.social:ripgrep
      atrun list --json @alice.bsky.social
    """
    from .run import fetch_yanks, list_records

    # Parse target: @handle or @handle:package
    if not target.startswith("@"):
        raise click.ClickException("Target must start with @ (e.g. @alice.bsky.social or @alice.bsky.social:package)")

    target = target[1:]  # strip leading @
    if ":" in target:
        handle, package = target.split(":", 1)
        # Strip @version if present
        if "@" in package:
            package = package.split("@")[0]
    else:
        handle = target
        package = None

    records = list_records(handle, package=package)

    if not records:
        if package:
            raise click.ClickException(f"No records found for {package} by @{handle}")
        raise click.ClickException(f"No records found by @{handle}")

    yanks = fetch_yanks(handle)

    if as_json:
        # Annotate records with yank status
        for rec in records:
            uri = rec.get("uri", "")
            if uri in yanks:
                rec["yanked"] = True
                reason = yanks[uri]
                if reason:
                    rec["yankReason"] = reason
        click.echo(json.dumps(records, indent=2))
        return

    if package:
        # Version list for a specific package
        for rec in records:
            ts = rec.get("timestamp", "")
            ts_str = f"  ({ts})" if ts else ""
            ver = rec.get("version", "")
            ver_str = f"@{ver}" if ver else ""
            yanked = " [yanked]" if rec.get("uri", "") in yanks else ""
            click.echo(f"@{handle}:{package}{ver_str}{ts_str}{yanked}")
    else:
        # Package list — show latest version of each package
        seen: dict[str, dict] = {}
        unnamed = []
        for rec in records:
            pkg = rec["package"]
            if not pkg:
                unnamed.append(rec)
                continue
            if pkg not in seen:
                seen[pkg] = rec
        for pkg, rec in seen.items():
            eco = f" ({rec['ecosystem']})" if rec["ecosystem"] else ""
            ver = rec.get("version", "")
            ver_str = f"@{ver}" if ver else ""
            yanked = " [yanked]" if rec.get("uri", "") in yanks else ""
            click.echo(f"@{handle}:{pkg}{ver_str}{eco}{yanked}")
        for rec in unnamed:
            eco = f" ({rec['ecosystem']})" if rec["ecosystem"] else ""
            ts = f"  ({rec['timestamp']})" if rec.get("timestamp") else ""
            yanked = " [yanked]" if rec.get("uri", "") in yanks else ""
            click.echo(f"{rec['uri']}{eco}{ts}{yanked}")


@cli.command()
@click.argument("target")
@click.option("--reason", default="", help="Reason for yanking this version.")
def yank(target: str, reason: str):
    """Yank a published package version.

    Marks a version as withdrawn by creating a dev.atpub.yank record
    that references the original. The original record stays intact —
    version chains and CIDs are preserved.

    Yanked versions are skipped when resolving @latest and marked
    in list output. Direct version references still work.

    TARGET is @handle:package@version or an AT URI.

    \b
    Examples:
      atrun yank @alice.bsky.social:cowsay@1.6.0
      atrun yank --reason "security vulnerability" @alice.bsky.social:cowsay@1.6.0
    """
    from datetime import datetime, timezone

    from .auth import load_session, refresh_session
    from .run import fetch_record

    result = fetch_record(target)
    at_info = result.get("at")
    if not at_info or "uri" not in at_info or "cid" not in at_info:
        raise click.ClickException("Cannot yank: record has no AT Protocol envelope.")

    session = load_session()
    did = session["did"]

    # Verify the record belongs to this user
    if at_info.get("did") and at_info["did"] != did:
        raise click.ClickException(f"Cannot yank: record belongs to {at_info.get('handle', at_info['did'])}, not you.")

    yank_record = {
        "$type": "dev.atpub.yank",
        "subject": {"uri": at_info["uri"], "cid": at_info["cid"]},
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if reason:
        yank_record["reason"] = reason

    import httpx
    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={
            "repo": did,
            "collection": "dev.atpub.yank",
            "record": yank_record,
        },
    )
    data = resp.json()
    if data.get("error") in ("ExpiredToken", "InvalidToken"):
        session = refresh_session(session)
        resp = httpx.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": did,
                "collection": "dev.atpub.yank",
                "record": yank_record,
            },
        )
        data = resp.json()

    if "uri" not in data:
        raise click.ClickException(f"Failed to create yank record: {data}")

    content = result.get("content", {})
    pkg = content.get("package", "?")
    ver = content.get("version", "?")
    click.echo(f"Yanked {pkg}@{ver}")


@cli.command()
@click.argument("target")
def unyank(target: str):
    """Remove a yank from a published package version.

    Deletes the dev.atpub.yank record, restoring the version to
    normal status.

    TARGET is @handle:package@version or an AT URI.

    \b
    Examples:
      atrun unyank @alice.bsky.social:cowsay@1.6.0
    """
    from .auth import load_session, refresh_session
    from .run import AT_URI_RE, fetch_record

    result = fetch_record(target)
    at_info = result.get("at")
    if not at_info or "uri" not in at_info:
        raise click.ClickException("Cannot unyank: record has no AT Protocol envelope.")

    session = load_session()
    did = session["did"]

    target_uri = at_info["uri"]

    # Find the yank record for this module record
    import httpx
    resp = httpx.get(
        "https://bsky.social/xrpc/com.atproto.repo.listRecords",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        params={"repo": did, "collection": "dev.atpub.yank", "limit": 100},
    )
    if resp.status_code != 200:
        raise click.ClickException("Failed to list yank records.")

    yank_uri = None
    for rec in resp.json().get("records", []):
        subject = rec.get("value", {}).get("subject", {})
        if subject.get("uri") == target_uri:
            yank_uri = rec["uri"]
            break

    if not yank_uri:
        raise click.ClickException("No yank record found for this version.")

    # Delete the yank record
    m = AT_URI_RE.match(yank_uri)
    if not m:
        raise click.ClickException(f"Invalid yank record URI: {yank_uri}")
    rkey = m.group(3)

    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.repo.deleteRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={
            "repo": did,
            "collection": "dev.atpub.yank",
            "rkey": rkey,
        },
    )
    data = resp.json() if resp.content else {}
    if data.get("error") in ("ExpiredToken", "InvalidToken"):
        session = refresh_session(session)
        resp = httpx.post(
            "https://bsky.social/xrpc/com.atproto.repo.deleteRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": did,
                "collection": "dev.atpub.yank",
                "rkey": rkey,
            },
        )

    content = result.get("content", {})
    pkg = content.get("package", "?")
    ver = content.get("version", "?")
    click.echo(f"Unyanked {pkg}@{ver}")


@cli.command()
@click.argument("uri")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints. The record will have no cryptographic verification.")
def resolve(uri: str, unsigned: bool):
    """Print resolved dependencies for a published record.

    Outputs dependency information in the ecosystem's native format:
    requirements.txt for Python, package list for Node.

    URI can be an AT URI (at://...) or an HTTPS URL to an XRPC getRecord
    endpoint.

    \b
    Examples:
      atrun resolve at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun resolve 'https://bsky.social/xrpc/com.atproto.repo.getRecord?repo=did:plc:abc123&collection=dev.atpub.manifest&rkey=3mgxyz'
    """
    from .run import fetch_record, generate_requirements

    record = fetch_record(uri, unsigned=unsigned)["content"]
    artifacts = record.get("artifacts", [])
    if not artifacts:
        raise click.ClickException("Record has no resolved packages.")
    click.echo(generate_requirements(artifacts, record=record))


@cli.command()
@click.argument("uri")
@click.option("--json", "as_json", is_flag=True, help="Output as structured JSON with 'at' (envelope) and 'content' sections.")
@click.option("--raw", is_flag=True, help="Print the full raw AT Protocol record as returned by the PDS.")
@click.option("--dist", "show_dist", is_flag=True, help="Print only the distribution artifact URL.")
@click.option("--registry", is_flag=True, help="Fetch full metadata from the ecosystem's package registry (PyPI, npm, JSR) instead of showing record metadata.")
@click.option("--versions", is_flag=True, help="Follow the derivedFrom chain to show version history.")
@click.option("--social", is_flag=True, help="Show social context: publisher profile and post engagement (likes, reposts, replies).")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
def info(uri: str, as_json: bool, raw: bool, show_dist: bool, registry: bool, versions: bool, social: bool, unsigned: bool):
    """Show metadata for a published package record.

    By default, displays metadata stored in the record itself: package name,
    version, description, license, url, ecosystem, and dependency count.
    Also shows AT Protocol envelope information (publisher, CID, timestamp)
    when available.

    With --registry, fetches full metadata from the ecosystem's package
    registry (wheel METADATA for Python, package.json for npm, meta.json
    for JSR).

    With --social, shows publisher profile (followers, bio) and engagement
    on the associated Bluesky post (likes, reposts, replies).

    With --json, outputs structured JSON with separate 'at' and 'content'
    sections (and 'social' when --social is used).

    \b
    Examples:
      atrun info at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun info --json at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun info --social at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun info --registry at://did:plc:abc123/dev.atpub.manifest/3mgxyz
    """
    from .ecosystems import detect_ecosystem_from_artifacts, get_ecosystem
    from .run import fetch_record, fetch_yanks

    result = fetch_record(uri, unsigned=unsigned)
    at_info = result["at"]
    record = result["content"]
    package = record.get("package", "")

    # Check yank status
    yank_reason = None
    if at_info and "uri" in at_info and "did" in at_info:
        yanks = fetch_yanks(at_info["did"])
        if at_info["uri"] in yanks:
            yank_reason = yanks[at_info["uri"]]

    if versions:
        from .run import fetch_record as _fetch

        chain = []
        current_at = at_info
        current_record = record
        seen = set()

        while True:
            version = current_record.get("version", "?")
            uri_str = current_at.get("uri", "") if current_at else ""
            ts = current_at.get("timestamp", "") if current_at else ""
            handle = current_at.get("handle", "") if current_at else ""
            cid = current_at.get("cid", "") if current_at else ""

            entry = {"version": version, "uri": uri_str, "timestamp": ts}
            if handle:
                entry["handle"] = handle
            if cid:
                entry["cid"] = cid
            chain.append(entry)

            # Follow derivedFrom (list of strongRefs, or legacy single dict)
            derived = current_record.get("derivedFrom")
            if not derived:
                break
            # Normalize: accept both list and legacy single-dict format
            if isinstance(derived, dict):
                derived = [derived]
            first = derived[0] if derived else None
            if not first or not first.get("uri"):
                break
            derived_uri = first["uri"]
            if derived_uri in seen:
                break  # cycle detection
            seen.add(derived_uri)

            try:
                result = _fetch(derived_uri)
                current_at = result["at"]
                current_record = result["content"]
            except Exception:
                chain.append({"version": "?", "uri": derived_uri, "error": "could not fetch"})
                break

        if as_json:
            click.echo(json.dumps(chain, indent=2))
        else:
            for i, entry in enumerate(chain):
                prefix = "* " if i == 0 else "  "
                ts = f"  ({entry['timestamp']})" if entry.get("timestamp") else ""
                handle = entry.get("handle", "")
                ver = entry.get("version", "?")
                shorthand = f"@{handle}:{package}@{ver}" if handle else f"{package}@{ver}"
                click.echo(f"{prefix}{shorthand}{ts}")
        return

    if raw:
        raw_output = {}
        if at_info:
            raw_output.update(at_info)
        raw_output["value"] = record
        click.echo(json.dumps(raw_output, indent=2))
        return

    if show_dist:
        artifacts = record.get("artifacts", [])
        pkg_entry = next((e for e in artifacts if e["name"] == package), None)
        if not pkg_entry:
            raise click.ClickException(f"Package '{package}' not found in artifacts list.")
        click.echo(pkg_entry["url"])
        return

    if registry:
        # Fetch full metadata from ecosystem registry
        artifacts = record.get("artifacts", [])
        pkg_entry = next((e for e in artifacts if e["name"] == package), None)
        if not pkg_entry:
            raise click.ClickException(f"Package '{package}' not found in artifacts list.")

        eco_name = detect_ecosystem_from_artifacts(record.get("artifacts", []), record=record)
        eco_mod = get_ecosystem(eco_name)
        metadata = eco_mod.fetch_metadata(pkg_entry["url"])

        if as_json:
            click.echo(json.dumps(metadata, indent=2))
            return

        for key, value in metadata.items():
            if key == "Description":
                continue
            if key == "Project-URL" and isinstance(value, list):
                for item in value:
                    label, _, url = item.partition(", ")
                    click.echo(f"{label}: {url}")
            elif isinstance(value, list):
                click.echo(f"{key}:")
                for item in value:
                    click.echo(f"  {item}")
            else:
                click.echo(f"{key}: {value}")
        return

    # Build output with AT envelope and content
    output: dict = {}

    if at_info:
        output["at"] = at_info
    elif unsigned:
        output["at"] = None

    content: dict = {}
    if package:
        content["package"] = package
    for field in ("version", "description", "license", "url"):
        if field in record:
            content[field] = record[field]

    artifacts = record.get("artifacts", [])

    if "packageType" in record:
        content["packageType"] = record["packageType"]
    if "tool" in record:
        content["tool"] = record["tool"]
    if "metadata" in record:
        content["metadata"] = record["metadata"]

    # Include hash of the main package
    pkg_entry = next((e for e in artifacts if e["name"] == package), None)
    if pkg_entry and "digest" in pkg_entry:
        content["digest"] = pkg_entry["digest"]

    derived = record.get("derivedFrom")
    if derived:
        # Normalize: accept both list and legacy single-dict format
        if isinstance(derived, dict):
            derived = [derived]
        content["derivedFrom"] = [ref.get("uri", "") for ref in derived]

    content["dependencies"] = len(artifacts)

    if yank_reason is not None:
        content["yanked"] = True
        if yank_reason:
            content["yankReason"] = yank_reason

    output["content"] = content

    # Fetch social info if requested
    social_info = None
    if social and at_info:
        from .run import fetch_social_info
        social_info = fetch_social_info(at_info)
        if social_info:
            output["social"] = social_info

    if as_json:
        click.echo(json.dumps(output, indent=2))
        return

    # Human-readable output — grouped logically
    # Package identity
    if "package" in content:
        click.echo(f"package: {content['package']}")
    if "version" in content:
        click.echo(f"version: {content['version']}")
    if "packageType" in content:
        click.echo(f"packageType: {content['packageType']}")

    # For package-less records (e.g. multi-image container), list resolved entries
    if not package and artifacts:
        click.echo("images:")
        for entry in artifacts:
            click.echo(f"  {entry['name']}:{entry.get('version', 'latest')}")

    if yank_reason is not None:
        reason_str = f": {yank_reason}" if yank_reason else ""
        click.echo(f"YANKED{reason_str}", err=True)

    # Description and metadata
    if "description" in content:
        click.echo(f"description: {content['description']}")
    if "license" in content:
        click.echo(f"license: {content['license']}")
    if "url" in content:
        click.echo(f"url: {content['url']}")

    # Integrity
    if "digest" in content:
        click.echo(f"hash: {content['hash']}")
    click.echo(f"dependencies: {content['dependencies']}")
    if "tool" in content:
        click.echo(f"tool: {content['tool']}")

    # Any remaining content fields not yet printed
    shown = {"package", "version", "packageType", "tool", "metadata", "description", "license", "url", "digest", "dependencies", "derivedFrom"}
    for key, value in content.items():
        if key not in shown:
            click.echo(f"{key}: {value}")

    # AT Protocol provenance
    if at_info:
        click.echo("")
        if "handle" in at_info:
            click.echo(f"publisher: {at_info['handle']} ({at_info['did']})")
        elif "did" in at_info:
            click.echo(f"publisher: {at_info['did']}")
        if "timestamp" in at_info:
            click.echo(f"timestamp: {at_info['timestamp']}")
        if "cid" in at_info:
            click.echo(f"cid: {at_info['cid']}")
        if "derivedFrom" in content:
            for uri in content["derivedFrom"]:
                click.echo(f"derivedFrom: {uri}")
    elif unsigned:
        click.echo("")
        click.echo("publisher: unsigned (no AT Protocol verification)")

    if social_info:
        pub = social_info.get("publisher")
        if pub:
            click.echo("")
            display = pub.get("displayName", "")
            handle = pub.get("handle", "")
            if display:
                click.echo(f"profile: {display} (@{handle})")
            else:
                click.echo(f"profile: @{handle}")
            click.echo(f"followers: {pub.get('followersCount', 0)}")
            desc = pub.get("description", "")
            if desc:
                # Show first line of bio
                click.echo(f"bio: {desc.splitlines()[0]}")

        post_info = social_info.get("post")
        if post_info:
            click.echo("")
            likes = post_info.get("likeCount", 0)
            reposts = post_info.get("repostCount", 0)
            replies_count = post_info.get("replyCount", 0)
            click.echo(f"post: {likes} likes, {reposts} reposts, {replies_count} replies")

            for reply in post_info.get("replies", []):
                click.echo(f"  @{reply['handle']}: {reply['text']}")


@cli.command()
@click.argument("target")
@click.option("--json", "as_json", is_flag=True, help="Output as structured JSON.")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
def verify(target: str, as_json: bool, unsigned: bool):
    """Verify a record's artifact hash without installing.

    Downloads the main package artifact, computes its SHA-256 hash,
    and compares it to the hash stored in the record.

    TARGET is @handle:package[@version] or an AT URI.

    \b
    Examples:
      atrun verify @alice.bsky.social:cowsay
      atrun verify --json @alice.bsky.social:cowsay@1.6.0
      atrun verify at://did:plc:abc123/dev.atpub.manifest/3mgxyz
    """
    from .run import fetch_record
    from .verify import HashMismatchError, verify_artifact

    result = fetch_record(target, unsigned=unsigned)
    record = result["content"]
    package = record.get("package")
    if not package:
        raise click.ClickException("Record has no 'package' field.")

    artifacts = record.get("artifacts", [])
    pkg_entry = next((e for e in artifacts if e["name"] == package), None)
    if not pkg_entry:
        raise click.ClickException(f"Package '{package}' not found in artifacts list.")

    pkg_hash = pkg_entry.get("digest", "")
    if not pkg_hash:
        raise click.ClickException(f"Package '{package}' has no hash in the record.")

    url = pkg_entry["url"]

    # Container images use digest verification instead of download
    if url.startswith("oci://"):
        from .ecosystems.container import verify_digest as _verify_container
        ref = url.removeprefix("oci://")
        click.echo(f"Verifying {package} from {ref}...", err=True)
        try:
            _verify_container(ref, pkg_hash)
        except SystemExit as exc:
            if as_json:
                click.echo(json.dumps({
                    "verified": False,
                    "package": package,
                    "url": url,
                    "error": str(exc),
                }, indent=2))
            else:
                click.echo(f"FAILED: {exc}", err=True)
            raise SystemExit(1)
        if as_json:
            click.echo(json.dumps({
                "verified": True,
                "package": package,
                "url": url,
                "digest": pkg_hash,
            }, indent=2))
        else:
            click.echo(f"Verified: {pkg_hash}")
        return

    click.echo(f"Verifying {package} from {url}...", err=True)

    try:
        verify_artifact(url, pkg_hash)
    except HashMismatchError as exc:
        if as_json:
            click.echo(json.dumps({
                "verified": False,
                "package": package,
                "url": url,
                "expected": exc.expected,
                "actual": exc.actual,
            }, indent=2))
        else:
            click.echo(f"FAILED: {exc}", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(json.dumps({
            "verified": True,
            "package": package,
            "url": url,
            "digest": pkg_hash,
        }, indent=2))
    else:
        click.echo(f"Verified: {pkg_hash}")


@cli.command()
@click.argument("uri")
@click.option("-d", "--directory", type=click.Path(), default=".", help="Directory to save artifacts to (default: current directory).")
@click.option("--deps/--no-deps", default=False, help="Also fetch all dependency artifacts (default: main package only).")
@click.option("--verify/--no-verify", "do_verify", default=True, help="Verify artifact hashes against the record (default: --verify).")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
def fetch(uri: str, directory: str, deps: bool, do_verify: bool, unsigned: bool):
    """Download and verify artifacts from an AT Protocol record.

    Fetches the main package artifact (or all dependencies with --deps),
    verifies hashes against the record, and saves to the target directory.
    Dependencies are downloaded in parallel.

    \b
    Examples:
      atrun fetch @alice.bsky.social:cowsay
      atrun fetch --deps @alice.bsky.social:cowsay
      atrun fetch -d ./artifacts @alice.bsky.social:cowsay
      atrun fetch --deps --no-verify @alice.bsky.social:cowsay
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from .run import fetch_record
    from .verify import HashMismatchError, _parse_hash, hash_bytes

    result = fetch_record(uri, unsigned=unsigned)
    record = result["content"]
    package = record.get("package")
    if not package:
        raise click.ClickException("Record has no 'package' field.")

    artifacts = record.get("artifacts", [])
    if not artifacts:
        raise click.ClickException("Record has no resolved packages.")

    if deps:
        entries = artifacts
    else:
        pkg_entry = next((e for e in artifacts if e["name"] == package), None)
        if not pkg_entry:
            raise click.ClickException(f"Package '{package}' not found in artifacts list.")
        entries = [pkg_entry]

    dest_dir = Path(directory)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Container images: use docker save instead of HTTP download
    eco_url = entries[0].get("url", "") if entries else ""
    if eco_url.startswith("oci://"):
        import subprocess

        click.echo(f"Fetching {len(entries)} image{'s' if len(entries) != 1 else ''} to {dest_dir}/", err=True)
        from .ecosystems.container import verify_digest as _verify_container
        failed = []
        for entry in entries:
            name = entry["name"]
            ref = entry["url"].removeprefix("oci://")
            pkg_hash = entry.get("digest", "")
            safe_name = name.replace("/", "_")
            dest = dest_dir / f"{safe_name}.tar"

            if do_verify and pkg_hash:
                try:
                    _verify_container(ref, pkg_hash)
                except SystemExit as exc:
                    click.echo(f"FAILED {name}: {exc}", err=True)
                    failed.append(name)
                    continue

            try:
                subprocess.run(
                    ["docker", "save", "-o", str(dest), ref],
                    check=True, capture_output=True, text=True,
                )
                click.echo(f"{dest}")
            except Exception as exc:
                click.echo(f"FAILED {name}: {exc}", err=True)
                failed.append(name)

        if failed:
            raise SystemExit(f"{len(failed)} image(s) failed")
        return

    click.echo(f"Fetching {len(entries)} artifact{'s' if len(entries) != 1 else ''} to {dest_dir}/", err=True)

    def _fetch_one(client: httpx.Client, entry: dict) -> tuple[str, Path | None, str | None]:
        name = entry["name"]
        url = entry["url"]
        filename = url.rsplit("/", 1)[-1]
        dest = dest_dir / filename
        expected_hash = entry.get("digest", "") or None if do_verify else None

        try:
            resp = client.get(url, follow_redirects=True)
            resp.raise_for_status()

            if expected_hash:
                algo, expected = _parse_hash(expected_hash)
                actual = hash_bytes(resp.content, algo)
                if actual != expected:
                    raise HashMismatchError(url, f"{algo}:{expected}", f"{algo}:{actual}")

            dest.write_bytes(resp.content)
            return name, dest, None
        except HashMismatchError as exc:
            return name, None, str(exc)
        except Exception as exc:
            return name, None, f"{name}: {exc}"

    failed = []
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_one, client, e): e for e in entries}
            for future in as_completed(futures):
                name, dest, error = future.result()
                if error:
                    click.echo(f"FAILED {name}: {error}", err=True)
                    failed.append(name)
                else:
                    click.echo(f"{dest}")

    if failed:
        raise SystemExit(f"{len(failed)} artifact(s) failed verification")


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("uri")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--deps", is_flag=True, help="Force frozen lockfile verification using the record's dependency graph. Errors if the record has no dependency data.")
@click.option("--no-deps", is_flag=True, help="Skip frozen lockfile verification even if the record has dependency data. Installs using the package manager's default resolution.")
@click.option("--verify/--no-verify", "do_verify", default=True, help="Verify the main package artifact hash before installing (default: --verify).")
@click.option("--engine", type=click.Choice(["pnpm", "bun", "npm", "docker", "crane"]), default=None, help="Package manager or container engine to use.")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
@click.option("--dry-run", "install_dry_run", is_flag=True, help="Print the install command without executing it.")
def install(uri: str, extra_args: tuple[str, ...], deps: bool, no_deps: bool, do_verify: bool, engine: str | None, unsigned: bool, install_dry_run: bool):
    """Install a package from an AT Protocol record.

    Fetches the record, detects the ecosystem, and installs the package
    using the appropriate tool (uv for Python, pnpm/bun/npm for Node,
    cargo for Rust).

    By default, uses frozen lockfile verification if the record contains a
    dependency graph (published with --deps), and falls back to direct
    install otherwise. Use --deps to require verification, or --no-deps
    to skip it.

    Extra arguments after the URI are passed through to the underlying
    package manager.

    \b
    Examples:
      atrun install at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun install --deps at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun install --no-deps at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun install at://did:plc:abc123/dev.atpub.manifest/3mgxyz -- --force
    """
    import shlex
    import subprocess
    import tempfile

    if deps and no_deps:
        raise click.ClickException("Cannot use both --deps and --no-deps.")

    from .ecosystems import detect_ecosystem_from_artifacts, get_ecosystem
    from .run import fetch_record, fetch_yanks, generate_requirements

    result = fetch_record(uri, unsigned=unsigned)
    at_info = result["at"]
    record = result["content"]
    package = record.get("package")
    if not package:
        raise click.ClickException("Record has no 'package' field.")
    artifacts = record.get("artifacts", [])
    if not artifacts:
        raise click.ClickException("Record has no resolved packages.")

    # Check yank status
    if at_info and "uri" in at_info and "did" in at_info:
        yanks = fetch_yanks(at_info["did"])
        if at_info["uri"] in yanks:
            reason = yanks[at_info["uri"]]
            reason_str = f": {reason}" if reason else ""
            raise click.ClickException(f"This version has been yanked{reason_str}. Use a different version or install via the dist URL directly.")

    eco_name = detect_ecosystem_from_artifacts(artifacts, record=record)
    eco_mod = get_ecosystem(eco_name)

    version = record.get("version", "")
    click.echo(f"Installing {package} {version} ({eco_name})")

    if eco_name == "container":
        from .ecosystems.container import verify_digest as _verify_container

        # Container: verify digest then docker pull each image
        for entry in artifacts:
            ref = f"{entry['name']}:{entry['version']}"
            pkg_hash = entry.get("digest", "")

            if do_verify and pkg_hash:
                click.echo(f"Verifying {entry['name']}...", err=True)
                _verify_container(ref, pkg_hash, engine or "docker")
                click.echo("Digest verified.", err=True)

            selected_engine = engine or "docker"
            digest_ref = f"{entry['name']}@{pkg_hash}" if pkg_hash else ref
            cmd = [selected_engine, "pull", digest_ref, *extra_args]
            if install_dry_run:
                import shlex as _shlex
                click.echo(_shlex.join(cmd))
                continue
            subprocess.run(cmd, check=True)
        return

    if eco_name == "python":
        # Python: use uv tool install with requirements file
        pkg_entry = next((e for e in artifacts if e["name"] == package), None)
        if not pkg_entry:
            raise click.ClickException(f"Package '{package}' not found in artifacts list.")

        requirements = generate_requirements(artifacts, record=record)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix="atrun-", delete=False) as f:
            f.write(requirements)
            req_path = f.name

        # Download and verify main package hash, then use file:// URL
        verified_path = None
        pkg_url = pkg_entry["url"]
        pkg_hash = pkg_entry.get("digest", "")

        if do_verify and pkg_hash:
            from .verify import HashMismatchError, download_and_verify

            click.echo(f"Verifying {package}...", err=True)
            try:
                verified_path = download_and_verify(pkg_url, pkg_hash)
            except HashMismatchError as exc:
                raise click.ClickException(str(exc))
            pkg_url = f"file://{verified_path}"
            click.echo("Hash verified.", err=True)
        elif do_verify and not pkg_hash:
            click.echo(f"Warning: no hash in record for {package}, skipping verification.", err=True)

        try:
            cmd = [
                "uv", "tool", "install",
                f"{package} @ {pkg_url}",
                "--with-requirements", req_path,
                *extra_args,
            ]

            if install_dry_run:
                click.echo(shlex.join(cmd))
                return

            subprocess.run(cmd, check=True)
        finally:
            if verified_path:
                verified_path.unlink(missing_ok=True)
    elif eco_name in ("rust", "go"):
        # Rust: verify artifact hash before cargo install (Go: skip, h1: tree hashes)
        if eco_name == "rust" and do_verify:
            pkg_entry = next((e for e in artifacts if e["name"] == package), None)
            pkg_hash = pkg_entry.get("digest", "") if pkg_entry else ""
            if pkg_hash:
                from .verify import HashMismatchError, verify_artifact

                click.echo(f"Verifying {package}...", err=True)
                try:
                    verify_artifact(pkg_entry["url"], pkg_hash)
                except HashMismatchError as exc:
                    raise click.ClickException(str(exc))
                click.echo("Hash verified.", err=True)
            elif pkg_entry:
                click.echo(f"Warning: no hash in record for {package}, skipping verification.", err=True)

        # Rust/Go: cargo install / go install
        cmd = eco_mod.generate_install_args(record) + list(extra_args)
        if install_dry_run:
            click.echo(shlex.join(cmd))
            return
        env = None
        if eco_name == "go":
            env = {**os.environ, "GO111MODULE": "on"}
        subprocess.run(cmd, check=True, env=env)
    else:
        # Node: determine whether to use verified install
        has_dep_info = any(e.get("dependencies") for e in artifacts)

        if deps and not has_dep_info:
            raise click.ClickException("--deps requested but record has no dependency graph.")

        use_verified = has_dep_info and not no_deps if not deps else True

        # Pass engine to node ecosystem functions
        engine_kwargs = {}
        if engine and eco_name == "node":
            engine_kwargs["engine"] = engine

        if use_verified:
            result = eco_mod.run_verified_install(record, extra_args=extra_args, dry_run=install_dry_run, do_verify=do_verify, **engine_kwargs)
            if install_dry_run and result:
                click.echo(shlex.join(result))
        else:
            # Direct install — verify hash then use local tarball
            pkg_entry = next((e for e in artifacts if e["name"] == package), None)
            verified_path = None
            pkg_spec = pkg_entry["url"] if pkg_entry else package

            if do_verify and pkg_entry:
                pkg_hash = pkg_entry.get("digest", "")
                if pkg_hash:
                    from .verify import HashMismatchError, download_and_verify

                    click.echo(f"Verifying {package}...", err=True)
                    try:
                        verified_path = download_and_verify(pkg_entry["url"], pkg_hash)
                    except HashMismatchError as exc:
                        raise click.ClickException(str(exc))
                    pkg_spec = f"file://{verified_path}"
                    click.echo("Hash verified.", err=True)
                else:
                    click.echo(f"Warning: no hash in record for {package}, skipping verification.", err=True)

            selected_engine = engine or eco_mod.DEFAULT_ENGINE
            cmd = [selected_engine, "install", "-g", pkg_spec, *extra_args]
            if install_dry_run:
                click.echo(shlex.join(cmd))
                return

            try:
                subprocess.run(cmd, check=True)
            finally:
                if verified_path:
                    verified_path.unlink(missing_ok=True)


@cli.command()
@click.argument("uri")
@click.option("--verify/--no-verify", "do_verify", default=True, help="Verify the main package artifact hash before running (default: --verify).")
@click.option("--engine", type=click.Choice(["pnpm", "bun", "npm", "docker", "crane"]), default=None, help="Package manager or container engine to use.")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
def run(uri: str, do_verify: bool, engine: str | None, unsigned: bool):
    """Run a package directly from an AT Protocol record.

    Fetches the record, installs dependencies into a temporary environment,
    and executes the package. The temporary environment is cleaned up after
    the command exits.

    For Python, downloads and verifies the artifact hash, then runs via uvx.
    For Node, uses the ecosystem's native run mechanism.

    \b
    Examples:
      atrun run at://did:plc:abc123/dev.atpub.manifest/3mgxyz
      atrun run --engine bun at://did:plc:abc123/dev.atpub.manifest/3mgxyz
    """
    from .run import run_module

    run_module(uri, unsigned=unsigned, engine=engine, do_verify=do_verify)
