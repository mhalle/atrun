"""Command-line interface for atrun.

Provides commands for publishing, inspecting, installing, and running
packages distributed via AT Protocol records.
"""

import getpass
import json
import sys
from pathlib import Path

import click


@click.group()
def cli():
    """Social package distribution on AT Protocol.

    Publish, inspect, install, and run packages from AT Protocol records.
    Supports Python (pip/uv), Node.js (npm/pnpm/bun), and Rust (cargo) ecosystems.

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
@click.option("--ecosystem", "eco", type=click.Choice(["python", "node", "rust"]), default=None, help="Target ecosystem. Auto-detected from lockfile content or dist URL if omitted.")
@click.option("--deps", is_flag=True, help="Include the full dependency graph in the record, enabling frozen lockfile verification on install.")
@click.option("--derived-from", "derived_from", help="AT URI, XRPC URL, or bsky.app URL of the record this derives from. Auto-detected from previous versions if omitted.")
@click.option("--no-derived-from", is_flag=True, help="Suppress automatic derivedFrom linking to previous versions.")
@click.option("--post", is_flag=True, help="Create a Bluesky post with a link card embedding the published record.")
@click.option("--dry-run", is_flag=True, help="Print the record as JSON without publishing to AT Protocol.")
def publish(lockfile: str | None, dist_file: Path | None, dist_url: str | None, eco: str | None, deps: bool, derived_from: str | None, no_derived_from: bool, post: bool, dry_run: bool):
    """Publish a package record to AT Protocol.

    Parses the lockfile, hashes the distribution artifact, extracts metadata
    (description, license, url) from the dist file, and creates a
    dev.atrun.module record on the authenticated user's AT Protocol repo.

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
        record = build_record(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url, ecosystem=eco, strip_deps=not deps, derived_from=derived_from)
        click.echo(json.dumps(record, indent=2))
        return

    record_uri, post_uri = do_publish(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url, ecosystem=eco, strip_deps=not deps, derived_from=derived_from, no_derived_from=no_derived_from, post=post)
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
    from .run import list_records

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

    if as_json:
        click.echo(json.dumps(records, indent=2))
        return

    if package:
        # Version list for a specific package
        for rec in records:
            ts = rec.get("timestamp", "")
            ts_str = f"  ({ts})" if ts else ""
            ver = rec.get("version", "")
            ver_str = f"@{ver}" if ver else ""
            click.echo(f"@{handle}:{package}{ver_str}{ts_str}")
    else:
        # Package list — show latest version of each package
        seen: dict[str, dict] = {}
        for rec in records:
            pkg = rec["package"]
            if pkg not in seen:
                seen[pkg] = rec
        for pkg, rec in seen.items():
            eco = f" ({rec['ecosystem']})" if rec["ecosystem"] else ""
            ver = rec.get("version", "")
            ver_str = f"@{ver}" if ver else ""
            click.echo(f"@{handle}:{pkg}{ver_str}{eco}")


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
      atrun resolve at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun resolve 'https://bsky.social/xrpc/com.atproto.repo.getRecord?repo=did:plc:abc123&collection=dev.atrun.module&rkey=3mgxyz'
    """
    from .run import fetch_record, generate_requirements

    record = fetch_record(uri, unsigned=unsigned)["content"]
    resolved = record.get("resolved", [])
    if not resolved:
        raise click.ClickException("Record has no resolved packages.")
    click.echo(generate_requirements(resolved, record=record))


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
      atrun info at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun info --json at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun info --social at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun info --registry at://did:plc:abc123/dev.atrun.module/3mgxyz
    """
    from .ecosystems import detect_ecosystem_from_record, get_ecosystem
    from .run import fetch_record

    result = fetch_record(uri, unsigned=unsigned)
    at_info = result["at"]
    record = result["content"]
    package = record.get("package")
    if not package:
        raise click.ClickException("Record has no 'package' field.")

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

            # Follow derivedFrom
            derived = current_record.get("derivedFrom")
            if not derived or not derived.get("uri"):
                break
            derived_uri = derived["uri"]
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
        resolved = record.get("resolved", [])
        pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
        if not pkg_entry:
            raise click.ClickException(f"Package '{package}' not found in resolved list.")
        click.echo(pkg_entry["url"])
        return

    if registry:
        # Fetch full metadata from ecosystem registry
        resolved = record.get("resolved", [])
        pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
        if not pkg_entry:
            raise click.ClickException(f"Package '{package}' not found in resolved list.")

        eco_name = detect_ecosystem_from_record(record)
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

    content: dict = {"package": package}
    for field in ("version", "description", "license", "url"):
        if field in record:
            content[field] = record[field]

    eco = record.get("ecosystem", {})
    eco_type = eco.get("$type", "")
    if "python" in eco_type:
        content["ecosystem"] = "python"
    elif "node" in eco_type:
        content["ecosystem"] = "node"
    elif "rust" in eco_type:
        content["ecosystem"] = "rust"

    # Include hash of the main package
    resolved = record.get("resolved", [])
    pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
    if pkg_entry and "hash" in pkg_entry:
        content["hash"] = pkg_entry["hash"]

    derived = record.get("derivedFrom")
    if derived:
        content["derivedFrom"] = derived.get("uri", "")

    content["dependencies"] = len(resolved)
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
    click.echo(f"package: {content['package']}")
    if "version" in content:
        click.echo(f"version: {content['version']}")
    if "ecosystem" in content:
        click.echo(f"ecosystem: {content['ecosystem']}")

    # Description and metadata
    if "description" in content:
        click.echo(f"description: {content['description']}")
    if "license" in content:
        click.echo(f"license: {content['license']}")
    if "url" in content:
        click.echo(f"url: {content['url']}")

    # Integrity
    if "hash" in content:
        click.echo(f"hash: {content['hash']}")
    click.echo(f"dependencies: {content['dependencies']}")

    # Any remaining content fields not yet printed
    shown = {"package", "version", "ecosystem", "description", "license", "url", "hash", "dependencies", "derivedFrom"}
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
            click.echo(f"derivedFrom: {content['derivedFrom']}")
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


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("uri")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--deps", is_flag=True, help="Force frozen lockfile verification using the record's dependency graph. Errors if the record has no dependency data.")
@click.option("--no-deps", is_flag=True, help="Skip frozen lockfile verification even if the record has dependency data. Installs using the package manager's default resolution.")
@click.option("--engine", type=click.Choice(["pnpm", "bun", "npm"]), default=None, help="Node.js package manager to use (default: pnpm).")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
@click.option("--dry-run", "install_dry_run", is_flag=True, help="Print the install command without executing it.")
def install(uri: str, extra_args: tuple[str, ...], deps: bool, no_deps: bool, engine: str | None, unsigned: bool, install_dry_run: bool):
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
      atrun install at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun install --deps at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun install --no-deps at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun install at://did:plc:abc123/dev.atrun.module/3mgxyz -- --force
    """
    import shlex
    import subprocess
    import tempfile

    if deps and no_deps:
        raise click.ClickException("Cannot use both --deps and --no-deps.")

    from .ecosystems import detect_ecosystem_from_record, get_ecosystem
    from .run import fetch_record, generate_requirements

    record = fetch_record(uri, unsigned=unsigned)["content"]
    package = record.get("package")
    if not package:
        raise click.ClickException("Record has no 'package' field.")
    resolved = record.get("resolved", [])
    if not resolved:
        raise click.ClickException("Record has no resolved packages.")

    eco_name = detect_ecosystem_from_record(record)
    eco_mod = get_ecosystem(eco_name)

    version = record.get("version", "")
    click.echo(f"Installing {package} {version} ({eco_name})")

    if eco_name == "python":
        # Python: use uv tool install with requirements file
        pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
        if not pkg_entry:
            raise click.ClickException(f"Package '{package}' not found in resolved list.")

        requirements = generate_requirements(resolved, record=record)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix="atrun-", delete=False) as f:
            f.write(requirements)
            req_path = f.name

        cmd = [
            "uv", "tool", "install",
            f"{package} @ {pkg_entry['url']}",
            "--with-requirements", req_path,
            *extra_args,
        ]

        if install_dry_run:
            click.echo(shlex.join(cmd))
            return

        subprocess.run(cmd, check=True)
    elif eco_name == "rust":
        # Rust: cargo install
        cmd = eco_mod.generate_install_args(record) + list(extra_args)
        if install_dry_run:
            click.echo(shlex.join(cmd))
            return
        subprocess.run(cmd, check=True)
    else:
        # Node: determine whether to use verified install
        has_dep_info = any(e.get("dependencies") for e in resolved)

        if deps and not has_dep_info:
            raise click.ClickException("--deps requested but record has no dependency graph.")

        use_verified = has_dep_info and not no_deps if not deps else True

        # Pass engine to node ecosystem functions
        engine_kwargs = {}
        if engine and eco_name == "node":
            engine_kwargs["engine"] = engine

        if use_verified:
            result = eco_mod.run_verified_install(record, extra_args=extra_args, dry_run=install_dry_run, **engine_kwargs)
            if install_dry_run and result:
                click.echo(shlex.join(result))
        else:
            # Direct install — let the package manager resolve deps
            cmd = eco_mod.generate_install_args(record, **engine_kwargs) + list(extra_args)
            if install_dry_run:
                click.echo(shlex.join(cmd))
                return
            subprocess.run(cmd, check=True)


@cli.command()
@click.argument("uri")
@click.option("--engine", type=click.Choice(["pnpm", "bun", "npm"]), default=None, help="Node.js package manager to use (default: pnpm).")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
def run(uri: str, engine: str | None, unsigned: bool):
    """Run a package directly from an AT Protocol record.

    Fetches the record, installs dependencies into a temporary environment,
    and executes the package. The temporary environment is cleaned up after
    the command exits.

    For Python, creates an isolated venv with hash-verified dependencies.
    For Node, uses the ecosystem's native run mechanism.

    \b
    Examples:
      atrun run at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun run --engine bun at://did:plc:abc123/dev.atrun.module/3mgxyz
    """
    from .run import run_module

    run_module(uri, unsigned=unsigned, engine=engine)
