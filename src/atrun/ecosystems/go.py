"""Go module ecosystem support (go.sum + proxy.golang.org)."""

from __future__ import annotations

import base64
import re

import httpx

LOCKFILE_EXTENSIONS = [".sum"]

PROXY_BASE = "https://proxy.golang.org"


def _module_download_url(module: str, version: str) -> str:
    """Build the proxy.golang.org download URL for a module."""
    # Go proxy requires uppercase letters to be escaped as !lowercase
    escaped = re.sub(r"[A-Z]", lambda m: f"!{m.group().lower()}", module)
    return f"{PROXY_BASE}/{escaped}/@v/{version}.zip"


def _convert_h1_hash(h1: str) -> str:
    """Convert Go's h1:base64 hash to sha256:hex format.

    Go's h1: prefix indicates SHA-256 of the module zip tree hash.
    """
    if h1.startswith("h1:"):
        b64 = h1[3:]
        raw = base64.b64decode(b64)
        return f"sha256:{raw.hex()}"
    return h1


def parse_lockfile(content: str) -> list[dict]:
    """Parse a go.sum file and return sorted dependency entries.

    Each line is: module version hash
    We skip /go.mod lines and deduplicate by (module, version).
    """
    entries = []
    seen = set()

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 3:
            continue

        module, version, hash_str = parts

        # Skip go.mod hashes — we want the module zip hashes
        if version.endswith("/go.mod"):
            continue

        dedup_key = (module, version)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        entry: dict = {
            "name": module,
            "version": version,
            "digest": _convert_h1_hash(hash_str),
            "urls": [_module_download_url(module, version)],
            "artifactType": "module",
        }
        entries.append(entry)

    entries.sort(key=lambda e: e["name"])
    return entries


def export_lockfile() -> str:
    """Read ./go.sum and return its content."""
    from pathlib import Path

    lock_path = Path("go.sum")
    if not lock_path.exists():
        raise SystemExit("go.sum not found in current directory.")
    return lock_path.read_text()


def build_metadata() -> dict:
    """Return ecosystem-specific metadata for the manifest.

    Reads the Go version from go.mod if available.
    """
    from pathlib import Path

    go_mod = Path("go.mod")
    if go_mod.exists():
        for line in go_mod.read_text().splitlines():
            line = line.strip()
            if line.startswith("go "):
                return {"goVersion": line.split()[1]}
    return {}


def generate_requirements(artifacts: list[dict]) -> str:
    """Format artifacts as module specs."""
    lines = []
    for entry in artifacts:
        lines.append(f"{entry['name']}@{entry['version']}")
    return "\n".join(lines)


def format_resolve_output(artifacts: list[dict]) -> str:
    """Format artifacts for output."""
    return generate_requirements(artifacts)


def generate_install_args(record: dict) -> list[str]:
    """Build go install command args."""
    package = record.get("package")
    artifacts = record.get("artifacts", [])
    pkg_entry = next((e for e in artifacts if e["name"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in artifacts list.")
    version = pkg_entry["version"]
    return ["go", "install", f"{package}@{version}"]


def generate_run_args(record: dict) -> list[str]:
    """Build args for running a Go module."""
    package = record.get("package")
    artifacts = record.get("artifacts", [])
    pkg_entry = next((e for e in artifacts if e["name"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in artifacts list.")
    version = pkg_entry["version"]
    return ["go", "run", f"{package}@{version}"]


def fetch_metadata(url: str) -> dict:
    """Fetch metadata from proxy.golang.org for a module.

    Uses the .info endpoint for version/timestamp and the .mod
    endpoint for the module declaration.
    """
    # Extract module and version from proxy URL
    # URL: https://proxy.golang.org/{module}/@v/{version}.zip
    m = re.search(r"proxy\.golang\.org/(.+)/@v/(.+)\.zip", url)
    if not m:
        raise ValueError(f"Cannot parse Go module URL: {url}")

    escaped_module = m.group(1)
    version = m.group(2)

    # Unescape module path (!x -> X)
    module = re.sub(r"!([a-z])", lambda m: m.group(1).upper(), escaped_module)

    result: dict[str, str | list[str]] = {
        "Name": module,
        "Version": version,
    }

    # Fetch .info for timestamp
    try:
        resp = httpx.get(f"{PROXY_BASE}/{escaped_module}/@v/{version}.info")
        if resp.status_code == 200:
            info = resp.json()
            if "Time" in info:
                result["Time"] = info["Time"]
    except Exception:
        pass

    # Fetch .mod for module info
    try:
        resp = httpx.get(f"{PROXY_BASE}/{escaped_module}/@v/{version}.mod")
        if resp.status_code == 200:
            mod_content = resp.text
            for line in mod_content.splitlines():
                line = line.strip()
                if line.startswith("go "):
                    result["GoVersion"] = line.split()[1]
    except Exception:
        pass

    return result


def extract_dist_metadata(url: str) -> dict:
    """Extract standardized metadata from a Go module proxy URL."""
    meta = fetch_metadata(url)
    result: dict[str, str] = {}
    if "Name" in meta:
        result["url"] = f"https://pkg.go.dev/{meta['Name']}"
    return result
