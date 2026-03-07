"""CLI entry point for atrun."""

import getpass
import json
import sys
from pathlib import Path

import click


@click.group()
def cli():
    """Social package distribution on AT Protocol."""


@cli.command()
@click.option("--handle", prompt="Bluesky handle", help="e.g. alice.bsky.social")
def login(handle: str):
    """Authenticate with Bluesky."""
    from .auth import login as do_login

    app_password = getpass.getpass("App password: ")
    session = do_login(handle, app_password)
    click.echo(f"Logged in as {session['handle']} ({session['did']})")


@cli.command()
@click.option("--lockfile", type=click.Path(), help="Lockfile path, or - for stdin. Omit to auto-export.")
@click.option("--dist-file", type=click.Path(exists=True, path_type=Path), help="Local distribution file to hash.")
@click.option("--dist-url", help="Public URL where the distribution is hosted.")
@click.option("--ecosystem", "eco", type=click.Choice(["python", "node", "deno"]), default=None, help="Ecosystem (auto-detected if omitted).")
@click.option("--permission", "permissions", multiple=True, help="Deno permissions (e.g. --permission read --permission env --permission net=example.com).")
@click.option("--deps", is_flag=True, help="Include dependency graph in the record.")
@click.option("--dry-run", is_flag=True, help="Print the record as JSON without publishing.")
def publish(lockfile: str | None, dist_file: Path | None, dist_url: str | None, eco: str | None, permissions: tuple[str, ...], deps: bool, dry_run: bool):
    """Publish resolved dependencies as an AT Protocol record.

    Without --lockfile, uses the ecosystem's default export.
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

    at_uri = do_publish(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url, ecosystem=eco, permissions=perms, strip_deps=not deps)
    click.echo(at_uri)


@cli.command()
@click.argument("at_uri")
def cat(at_uri: str):
    """Fetch an AT URI and print the full record as JSON."""
    from .run import fetch_record

    record = fetch_record(at_uri)
    click.echo(json.dumps(record, indent=2))


@cli.command()
@click.argument("at_uri")
def resolve(at_uri: str):
    """Fetch an AT URI and print resolved dependencies to stdout."""
    from .run import fetch_record, generate_requirements

    record = fetch_record(at_uri)
    resolved = record.get("resolved", [])
    if not resolved:
        raise click.ClickException("Record has no resolved packages.")
    click.echo(generate_requirements(resolved, record=record))


@cli.command()
@click.argument("at_uri")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--registry", is_flag=True, help="Fetch full metadata from the ecosystem registry.")
def info(at_uri: str, as_json: bool, registry: bool):
    """Show package metadata for a published module."""
    from .ecosystems import detect_ecosystem_from_record, get_ecosystem
    from .run import fetch_record

    record = fetch_record(at_uri)
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

    # Show metadata from the record itself
    metadata = {"package": package}
    for field in ("version", "description", "license", "url"):
        if field in record:
            metadata[field] = record[field]

    eco = record.get("ecosystem", {})
    eco_type = eco.get("$type", "")
    if "python" in eco_type:
        metadata["ecosystem"] = "python"
    elif "deno" in eco_type:
        metadata["ecosystem"] = "deno"
    elif "node" in eco_type:
        metadata["ecosystem"] = "node"

    resolved = record.get("resolved", [])
    metadata["dependencies"] = len(resolved)

    if as_json:
        click.echo(json.dumps(metadata, indent=2))
        return

    for key, value in metadata.items():
        click.echo(f"{key}: {value}")


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("at_uri")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--deps", is_flag=True, help="Force frozen lockfile verification (error if no dep graph).")
@click.option("--no-deps", is_flag=True, help="Skip lockfile verification even if dep graph is available.")
@click.option("--dry-run", "install_dry_run", is_flag=True, help="Print the install command without running it.")
def install(at_uri: str, extra_args: tuple[str, ...], deps: bool, no_deps: bool, install_dry_run: bool):
    """Install a module from an AT URI.

    By default, uses frozen lockfile verification if the record has a
    dependency graph, and falls back to direct install otherwise.

    Extra arguments are passed through to the ecosystem's install command.
    """
    import shlex
    import subprocess
    import tempfile

    if deps and no_deps:
        raise click.ClickException("Cannot use both --deps and --no-deps.")

    from .ecosystems import detect_ecosystem_from_record, get_ecosystem
    from .run import fetch_record, generate_requirements

    record = fetch_record(at_uri)
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
@click.argument("at_uri")
def run(at_uri: str):
    """Run a module from an AT URI."""
    from .run import run_module

    run_module(at_uri)
