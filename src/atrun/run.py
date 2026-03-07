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


def generate_requirements(resolved: list[dict], record: dict | None = None) -> str:
    """Generate resolved output appropriate to the record's ecosystem.

    Falls back to Python requirements.txt format if no record is provided.
    """
    if record is not None:
        from .ecosystems import detect_ecosystem_from_record, get_ecosystem
        eco_name = detect_ecosystem_from_record(record)
        eco_mod = get_ecosystem(eco_name)
        return eco_mod.format_resolve_output(resolved)

    # Legacy fallback: Python requirements.txt format
    lines = []
    for entry in resolved:
        name = entry["packageName"]
        url = entry["url"]
        hash_str = entry.get("hash", entry.get("sha256", ""))
        if ":" not in hash_str:
            hash_str = f"sha256:{hash_str}"
        lines.append(f"{name} @ {url} --hash={hash_str}")
    return "\n".join(lines)


def run_module(at_uri: str) -> None:
    """Fetch an atrun record and run it in a temporary environment."""
    from .ecosystems import detect_ecosystem_from_record, get_ecosystem

    record = fetch_record(at_uri)
    resolved = record.get("resolved", [])
    if not resolved:
        raise SystemExit("Record has no resolved packages.")

    package = record.get("package")
    if not package:
        raise SystemExit("Record has no 'package' field — cannot determine what to run.")

    eco_name = detect_ecosystem_from_record(record)
    eco_mod = get_ecosystem(eco_name)

    if eco_name == "python":
        # Python: use venv + uv pip install
        requirements = eco_mod.generate_requirements(resolved)

        with tempfile.TemporaryDirectory(prefix="atrun-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            req_file = tmpdir_path / "requirements.txt"
            req_file.write_text(requirements)

            venv_path = tmpdir_path / ".venv"

            subprocess.run(
                ["uv", "venv", str(venv_path)],
                check=True,
            )

            subprocess.run(
                [
                    "uv", "pip", "install",
                    "--require-hashes",
                    "--python", str(venv_path / "bin" / "python"),
                    "-r", str(req_file),
                ],
                check=True,
            )

            subprocess.run(
                [
                    "uv", "run",
                    "--python", str(venv_path / "bin" / "python"),
                    package,
                ],
                check=True,
            )
    else:
        # Node/Deno: run directly
        cmd = eco_mod.generate_run_args(record)
        subprocess.run(cmd, check=True)
