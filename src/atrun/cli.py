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
    Supports Python (pip/uv), Node.js (npm/pnpm), and Deno ecosystems.

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
@click.option("--ecosystem", "eco", type=click.Choice(["python", "node", "deno"]), default=None, help="Target ecosystem. Auto-detected from lockfile content or dist URL if omitted.")
@click.option("--permission", "permissions", multiple=True, help="Deno permission to grant (e.g. --permission read --permission env --permission net=example.com). May be specified multiple times.")
@click.option("--deps", is_flag=True, help="Include the full dependency graph in the record, enabling frozen lockfile verification on install.")
@click.option("--post", is_flag=True, help="Create a Bluesky post with a link card embedding the published record.")
@click.option("--dry-run", is_flag=True, help="Print the record as JSON without publishing to AT Protocol.")
def publish(lockfile: str | None, dist_file: Path | None, dist_url: str | None, eco: str | None, permissions: tuple[str, ...], deps: bool, post: bool, dry_run: bool):
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

    perms = list(permissions) if permissions else None

    if dry_run:
        record = build_record(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url, ecosystem=eco, permissions=perms, strip_deps=not deps)
        click.echo(json.dumps(record, indent=2))
        return

    at_uri = do_publish(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url, ecosystem=eco, permissions=perms, strip_deps=not deps, post=post)
    click.echo(at_uri)


@cli.command()
@click.argument("uri")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints. The record will have no cryptographic verification.")
def resolve(uri: str, unsigned: bool):
    """Print resolved dependencies for a published record.

    Outputs dependency information in the ecosystem's native format:
    requirements.txt for Python, package list for Node/Deno.

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
@click.option("--registry", is_flag=True, help="Fetch full metadata from the ecosystem's package registry (PyPI, npm, JSR) instead of showing record metadata.")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
def info(uri: str, as_json: bool, registry: bool, unsigned: bool):
    """Show metadata for a published package record.

    By default, displays metadata stored in the record itself: package name,
    version, description, license, url, ecosystem, and dependency count.
    Also shows AT Protocol envelope information (publisher, CID, timestamp)
    when available.

    With --registry, fetches full metadata from the ecosystem's package
    registry (wheel METADATA for Python, package.json for npm, meta.json
    for JSR).

    With --json, outputs structured JSON with separate 'at' and 'content'
    sections.

    \b
    Examples:
      atrun info at://did:plc:abc123/dev.atrun.module/3mgxyz
      atrun info --json at://did:plc:abc123/dev.atrun.module/3mgxyz
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
    elif "deno" in eco_type:
        content["ecosystem"] = "deno"
    elif "node" in eco_type:
        content["ecosystem"] = "node"

    resolved = record.get("resolved", [])
    content["dependencies"] = len(resolved)
    output["content"] = content

    if as_json:
        click.echo(json.dumps(output, indent=2))
        return

    # Human-readable output
    if at_info:
        if "handle" in at_info:
            click.echo(f"publisher: {at_info['handle']} ({at_info['did']})")
        elif "did" in at_info:
            click.echo(f"publisher: {at_info['did']}")
        if "cid" in at_info:
            click.echo(f"cid: {at_info['cid']}")
        if "timestamp" in at_info:
            click.echo(f"timestamp: {at_info['timestamp']}")
    elif unsigned:
        click.echo("publisher: unsigned (no AT Protocol verification)")

    for key, value in content.items():
        click.echo(f"{key}: {value}")


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("uri")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--deps", is_flag=True, help="Force frozen lockfile verification using the record's dependency graph. Errors if the record has no dependency data.")
@click.option("--no-deps", is_flag=True, help="Skip frozen lockfile verification even if the record has dependency data. Installs using the package manager's default resolution.")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
@click.option("--dry-run", "install_dry_run", is_flag=True, help="Print the install command without executing it.")
def install(uri: str, extra_args: tuple[str, ...], deps: bool, no_deps: bool, unsigned: bool, install_dry_run: bool):
    """Install a package from an AT Protocol record.

    Fetches the record, detects the ecosystem, and installs the package
    using the appropriate tool (uv for Python, pnpm for Node, deno for Deno).

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
    else:
        # Node/Deno: determine whether to use verified install
        has_dep_info = any(e.get("dependencies") for e in resolved)

        if deps and not has_dep_info:
            raise click.ClickException("--deps requested but record has no dependency graph.")

        use_verified = has_dep_info and not no_deps if not deps else True

        if use_verified:
            result = eco_mod.run_verified_install(record, extra_args=extra_args, dry_run=install_dry_run)
            if install_dry_run and result:
                click.echo(shlex.join(result))
        else:
            # Direct install — let the package manager resolve deps
            cmd = eco_mod.generate_install_args(record) + list(extra_args)
            if install_dry_run:
                click.echo(shlex.join(cmd))
                return
            subprocess.run(cmd, check=True)


@cli.command()
@click.argument("uri")
@click.option("--unsigned", is_flag=True, help="Allow plain HTTPS URLs that are not AT Protocol XRPC endpoints.")
def run(uri: str, unsigned: bool):
    """Run a package directly from an AT Protocol record.

    Fetches the record, installs dependencies into a temporary environment,
    and executes the package. The temporary environment is cleaned up after
    the command exits.

    For Python, creates an isolated venv with hash-verified dependencies.
    For Node/Deno, uses the ecosystem's native run mechanism.

    \b
    Examples:
      atrun run at://did:plc:abc123/dev.atrun.module/3mgxyz
    """
    from .run import run_module

    run_module(uri, unsigned=unsigned)
