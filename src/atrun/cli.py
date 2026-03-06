"""CLI entry point for atrun."""

import getpass
import json
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
@click.argument("directory", default=".", type=click.Path(exists=True, path_type=Path))
@click.option("--python-version", help="Python version (e.g. 3.12)")
@click.option("--platform", help="Platform (e.g. linux-x86_64)")
@click.option("--wheel", type=click.Path(exists=True, path_type=Path), help="Local wheel file to include.")
@click.option("--wheel-url", help="Public URL where the wheel is hosted.")
@click.option("--dry-run", is_flag=True, help="Print the record as JSON without publishing.")
def publish(directory: Path, python_version: str | None, platform: str | None, wheel: Path | None, wheel_url: str | None, dry_run: bool):
    """Publish uv.lock as an AT Protocol record."""
    from .publish import build_record, publish as do_publish

    lock_path = directory / "uv.lock"
    if not lock_path.exists():
        raise click.ClickException(f"No uv.lock found in {directory}")

    if bool(wheel) != bool(wheel_url):
        raise click.ClickException("--wheel and --wheel-url must be used together.")

    if dry_run:
        record = build_record(lock_path, python_version=python_version, platform=platform, wheel_path=wheel, wheel_url=wheel_url)
        click.echo(json.dumps(record, indent=2))
        return

    at_uri = do_publish(lock_path, python_version=python_version, platform=platform, wheel_path=wheel, wheel_url=wheel_url)
    click.echo(at_uri)


@cli.command()
@click.argument("at_uri")
def run(at_uri: str):
    """Run a module from an AT URI."""
    from .run import run_module

    run_module(at_uri)
