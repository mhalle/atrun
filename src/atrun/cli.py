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
@click.option("--lockfile", type=click.Path(), help="pylock.toml file, or - for stdin. Omit to run uv export.")
@click.option("--dist-file", type=click.Path(exists=True, path_type=Path), help="Local distribution file to hash.")
@click.option("--dist-url", help="Public URL where the distribution is hosted.")
@click.option("--dry-run", is_flag=True, help="Print the record as JSON without publishing.")
def publish(lockfile: str | None, dist_file: Path | None, dist_url: str | None, dry_run: bool):
    """Publish resolved dependencies as an AT Protocol record.

    Without --lockfile, runs uv export to get the resolved lockfile.
    """
    from .publish import build_record, publish as do_publish

    lockfile_str = None
    if lockfile == "-":
        lockfile_str = sys.stdin.read()
    elif lockfile:
        lockfile_str = Path(lockfile).read_text()

    if dry_run:
        record = build_record(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url)
        click.echo(json.dumps(record, indent=2))
        return

    at_uri = do_publish(lockfile=lockfile_str, dist_file=dist_file, dist_url=dist_url)
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
    """Fetch an AT URI and print requirements.txt to stdout."""
    from .run import fetch_record, generate_requirements

    record = fetch_record(at_uri)
    resolved = record.get("resolved", [])
    if not resolved:
        raise click.ClickException("Record has no resolved packages.")
    click.echo(generate_requirements(resolved))


@cli.command()
@click.argument("at_uri")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def info(at_uri: str, as_json: bool):
    """Show package metadata for a published module."""
    from .run import fetch_record
    from .wheel import fetch_wheel_metadata

    record = fetch_record(at_uri)
    package = record.get("package")
    if not package:
        raise click.ClickException("Record has no 'package' field.")
    resolved = record.get("resolved", [])

    pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
    if not pkg_entry:
        raise click.ClickException(f"Package '{package}' not found in resolved list.")

    metadata = fetch_wheel_metadata(pkg_entry["url"])

    if as_json:
        click.echo(json.dumps(metadata, indent=2))
        return

    for key, value in metadata.items():
        if key == "Description":
            continue
        if isinstance(value, list):
            click.echo(f"{key}:")
            for item in value:
                click.echo(f"  {item}")
        else:
            click.echo(f"{key}: {value}")


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("at_uri")
@click.argument("uv_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--dry-run", "install_dry_run", is_flag=True, help="Print the uv command without running it.")
def install(at_uri: str, uv_args: tuple[str, ...], install_dry_run: bool):
    """Install a module as a uv tool from an AT URI.

    Extra arguments are passed through to uv tool install.
    """
    import shlex
    import subprocess
    import tempfile

    from .run import fetch_record, generate_requirements

    record = fetch_record(at_uri)
    package = record.get("package")
    if not package:
        raise click.ClickException("Record has no 'package' field.")
    resolved = record.get("resolved", [])
    if not resolved:
        raise click.ClickException("Record has no resolved packages.")

    pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
    if not pkg_entry:
        raise click.ClickException(f"Package '{package}' not found in resolved list.")

    requirements = generate_requirements(resolved)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix="atrun-", delete=False) as f:
        f.write(requirements)
        req_path = f.name

    cmd = [
        "uv", "tool", "install",
        f"{package} @ {pkg_entry['url']}",
        "--with-requirements", req_path,
        *uv_args,
    ]

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
