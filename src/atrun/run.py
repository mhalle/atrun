"""Fetch and run an atrun module from an AT URI."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import httpx

AT_URI_RE = re.compile(r"^at://([^/]+)/([^/]+)/([^/]+)$")


def resolve_pds_url(handle_or_did: str) -> str:
    """Resolve a handle or DID to a PDS base URL."""
    if handle_or_did.startswith("did:"):
        did = handle_or_did
    else:
        # Resolve handle to DID
        resp = httpx.get(
            "https://bsky.social/xrpc/com.atproto.identity.resolveHandle",
            params={"handle": handle_or_did},
        )
        resp.raise_for_status()
        did = resp.json()["did"]

    # For now, use bsky.social as PDS — works for most users
    return f"https://bsky.social", did


def fetch_record(at_uri: str) -> dict:
    """Fetch a record from an AT URI."""
    m = AT_URI_RE.match(at_uri)
    if not m:
        raise SystemExit(f"Invalid AT URI: {at_uri}")

    authority, collection, rkey = m.groups()
    pds_url, did = resolve_pds_url(authority)

    resp = httpx.get(
        f"{pds_url}/xrpc/com.atproto.repo.getRecord",
        params={"repo": did, "collection": collection, "rkey": rkey},
    )
    resp.raise_for_status()
    return resp.json()["value"]


def generate_requirements(resolved: list[dict]) -> str:
    """Generate a requirements.txt with --hash pins from resolved entries."""
    lines = []
    for entry in resolved:
        name = entry["packageName"]
        version = entry["packageVersion"]
        sha256 = entry["sha256"]
        url = entry["url"]
        lines.append(f"{name}=={version} --hash=sha256:{sha256} @ {url}")
    return "\n".join(lines)


def run_module(at_uri: str) -> None:
    """Fetch an atrun record and run it in a temporary environment."""
    record = fetch_record(at_uri)
    resolved = record.get("resolved", [])
    if not resolved:
        raise SystemExit("Record has no resolved packages.")

    requirements = generate_requirements(resolved)

    with tempfile.TemporaryDirectory(prefix="atrun-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        req_file = tmpdir_path / "requirements.txt"
        req_file.write_text(requirements)

        venv_path = tmpdir_path / ".venv"

        # Create venv
        subprocess.run(
            ["uv", "venv", str(venv_path)],
            check=True,
        )

        # Install with hash verification
        subprocess.run(
            [
                "uv", "pip", "install",
                "--require-hashes",
                "--python", str(venv_path / "bin" / "python"),
                "-r", str(req_file),
            ],
            check=True,
        )

        # Find the root package (first in the resolved list by convention,
        # or we can try to detect which one has console_scripts)
        # For now, use the first package as the entry point
        root_package = resolved[0]["packageName"]

        # Run via uv
        subprocess.run(
            [
                "uv", "run",
                "--python", str(venv_path / "bin" / "python"),
                root_package,
            ],
            check=True,
        )
