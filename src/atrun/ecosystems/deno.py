"""Deno ecosystem support."""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from pathlib import Path

import httpx

ECOSYSTEM_TYPE = "dev.atrun.module#denoEcosystem"
LOCKFILE_EXTENSIONS = [".lock"]


def _hex_to_sri(hash_str: str) -> str:
    """Convert algo:hex format back to SRI (algo-base64)."""
    algo, hex_hash = hash_str.split(":", 1)
    raw = bytes.fromhex(hex_hash)
    b64 = base64.b64encode(raw).decode()
    return f"{algo}-{b64}"


def _convert_sri_hash(sri: str) -> str:
    """Convert SRI hash (sha512-base64) to algo:hex format."""
    if ":" not in sri and "-" not in sri:
        return sri
    if "-" in sri:
        algo, b64 = sri.split("-", 1)
        hex_hash = base64.b64decode(b64).hex()
        return f"{algo}:{hex_hash}"
    return sri


def parse_lockfile(content: str) -> list[dict]:
    """Parse deno.lock (JSON) and return sorted dependency entries."""
    data = json.loads(content)

    # deno.lock v4 nests under "packages", v5 uses top-level "npm"/"jsr"
    packages = data.get("packages", {})

    entries = []

    # JSR packages
    jsr = packages.get("jsr", {}) or data.get("jsr", {})
    for key, info in jsr.items():
        # key format: "@scope/name@version"
        at_idx = key.rfind("@", 1)
        if at_idx == -1:
            continue
        name = key[:at_idx]
        version = key[at_idx + 1:]

        integrity = info.get("integrity", "")
        hash_str = _convert_sri_hash(integrity) if integrity else ""

        url = f"https://jsr.io/{name}/{version}"

        if hash_str:
            entries.append({
                "packageName": name,
                "packageVersion": version,
                "hash": hash_str,
                "url": url,
            })

    # npm packages used via Deno
    npm = packages.get("npm", {}) or data.get("npm", {})

    # Build version lookup for resolving unversioned dep references
    npm_versions: dict[str, list[str]] = {}
    for key in npm:
        at_idx = key.rfind("@", 1)
        if at_idx == -1:
            continue
        n = key[:at_idx]
        v = key[at_idx + 1:]
        npm_versions.setdefault(n, []).append(v)

    for key, info in npm.items():
        # key format: "package@version"
        at_idx = key.rfind("@", 1)
        if at_idx == -1:
            continue
        name = key[:at_idx]
        version = key[at_idx + 1:]

        integrity = info.get("integrity", "")
        hash_str = _convert_sri_hash(integrity) if integrity else ""

        pkg_basename = name.split("/")[-1]
        url = f"https://registry.npmjs.org/{name}/-/{pkg_basename}-{version}.tgz"

        # Extract dependencies, resolve to name@version format
        deps = []
        for dep_ref in info.get("dependencies", []):
            if "@" in dep_ref[1:]:
                # Already versioned: "string-width@2.1.1"
                deps.append(dep_ref)
            else:
                # Unversioned: "get-stdin" — resolve to the only available version
                dep_versions = npm_versions.get(dep_ref, [])
                if len(dep_versions) == 1:
                    deps.append(f"{dep_ref}@{dep_versions[0]}")
                elif dep_versions:
                    deps.append(f"{dep_ref}@{dep_versions[0]}")

        if hash_str:
            entry = {
                "packageName": name,
                "packageVersion": version,
                "hash": hash_str,
                "url": url,
            }
            if deps:
                entry["dependencies"] = sorted(deps)
            entries.append(entry)

    entries.sort(key=lambda e: e["packageName"])
    return entries


def export_lockfile() -> str:
    """Read ./deno.lock and return its content."""
    from pathlib import Path
    lock_path = Path("deno.lock")
    if not lock_path.exists():
        raise SystemExit("deno.lock not found in current directory.")
    return lock_path.read_text()


def build_ecosystem_value(permissions: list[str] | None = None) -> dict:
    """Return the ecosystem object for an AT Protocol record."""
    value: dict = {"$type": ECOSYSTEM_TYPE, "runtime": "deno"}
    if permissions:
        value["permissions"] = permissions
    return value


def _permission_flags(record: dict) -> list[str]:
    """Build --allow-X flags from the record's ecosystem permissions."""
    eco = record.get("ecosystem", {})
    permissions = eco.get("permissions")
    if not permissions:
        return ["--allow-all"]
    flags = []
    for perm in permissions:
        # "read" -> "--allow-read", "net=example.com" -> "--allow-net=example.com"
        flags.append(f"--allow-{perm}")
    return flags


def generate_requirements(resolved: list[dict]) -> str:
    """Format resolved deps as package specs."""
    lines = []
    for entry in resolved:
        name = entry["packageName"]
        version = entry["packageVersion"]
        url = entry["url"]
        if url.startswith("https://jsr.io/"):
            lines.append(f"jsr:{name}@{version}")
        else:
            lines.append(f"npm:{name}@{version}")
    return "\n".join(lines)


def generate_install_args(record: dict) -> list[str]:
    """Build deno install command args."""
    package = record.get("package")
    resolved = record.get("resolved", [])
    pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in resolved list.")
    version = pkg_entry["packageVersion"]
    flags = _permission_flags(record)
    return ["deno", "install", "-g", *flags, f"npm:{package}@{version}"]


def generate_run_args(record: dict) -> list[str]:
    """Build args for running a Deno package."""
    package = record.get("package")
    resolved = record.get("resolved", [])
    pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in resolved list.")
    version = pkg_entry["packageVersion"]
    flags = _permission_flags(record)
    return ["deno", "run", *flags, f"npm:{package}@{version}"]


def fetch_metadata(url: str) -> dict:
    """Fetch metadata from a JSR or npm registry URL."""
    if url.startswith("https://jsr.io/"):
        # JSR: fetch meta.json
        parts = url.rstrip("/").split("/")
        # URL: https://jsr.io/@scope/name/version
        scope_name = "/".join(parts[3:5])  # @scope/name
        meta_url = f"https://jsr.io/{scope_name}/meta.json"
        resp = httpx.get(meta_url, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        result: dict[str, str | list[str]] = {}
        if "name" in data:
            result["Name"] = data["name"]
        if "latest" in data:
            result["Version"] = data["latest"]
        if "description" in data:
            result["Description"] = data["description"]
        return result
    else:
        # npm tarball — delegate to node ecosystem
        from .node import fetch_metadata as node_fetch
        return node_fetch(url)


def _build_deno_lockfile(record: dict) -> str:
    """Reconstruct a deno.lock from the record's resolved entries."""
    package = record["package"]
    resolved = record["resolved"]

    pkg_entry = next(e for e in resolved if e["packageName"] == package)
    version = pkg_entry["packageVersion"]
    pkg_spec = f"npm:{package}@{version}"

    # Build version count for each package name (for dep reference format)
    name_versions: dict[str, list[str]] = {}
    for entry in resolved:
        name_versions.setdefault(entry["packageName"], []).append(entry["packageVersion"])

    npm_entries = {}
    for entry in resolved:
        name = entry["packageName"]
        ver = entry["packageVersion"]
        key = f"{name}@{ver}"
        sri = _hex_to_sri(entry["hash"])

        npm_info: dict = {"integrity": sri}

        # Dependencies: use "name" when only one version, "name@version" otherwise
        deps = entry.get("dependencies", [])
        if deps:
            deno_deps = []
            for dep_str in deps:
                at_idx = dep_str.rfind("@", 1)
                dep_name = dep_str[:at_idx]
                dep_ver = dep_str[at_idx + 1:]
                if len(name_versions.get(dep_name, [])) == 1:
                    deno_deps.append(dep_name)
                else:
                    deno_deps.append(f"{dep_name}@{dep_ver}")
            npm_info["dependencies"] = deno_deps

        if name == package:
            npm_info["bin"] = True

        npm_entries[key] = npm_info

    lock = {
        "version": "5",
        "specifiers": {pkg_spec: version},
        "npm": npm_entries,
        "workspace": {
            "dependencies": [pkg_spec],
        },
    }

    return json.dumps(lock, indent=2)


def run_verified_install(record: dict, extra_args: tuple[str, ...] = (), dry_run: bool = False) -> list[str] | None:
    """Install via deno with a reconstructed lockfile and --frozen.

    1. Reconstruct deno.lock from record (with integrity + deps)
    2. deno install --frozen (verifies integrity)
    3. deno install -g --frozen (installs globally from verified cache)
    """
    import click

    package = record.get("package")
    resolved = record.get("resolved", [])

    pkg_entry = next((e for e in resolved if e["packageName"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in resolved list.")
    version = pkg_entry["packageVersion"]
    pkg_spec = f"npm:{package}@{version}"

    # Check if record has dependency info for frozen lockfile install
    has_deps = any(e.get("dependencies") for e in resolved)
    flags = _permission_flags(record)

    if not has_deps:
        # Fallback: direct install without lockfile verification
        cmd = ["deno", "install", "-g", *flags, pkg_spec, *extra_args]
        if dry_run:
            return cmd
        import click
        click.echo("No dependency graph in record — installing without lockfile verification")
        subprocess.run(cmd, check=True)
        return None

    if dry_run:
        return ["deno", "install", "-g", *flags, "--frozen", pkg_spec, *extra_args]

    with tempfile.TemporaryDirectory(prefix="atrun-deno-") as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write deno.json
        deno_json = {"imports": {package: pkg_spec}}
        (tmpdir_path / "deno.json").write_text(json.dumps(deno_json, indent=2))

        # Write reconstructed deno.lock
        lockfile_content = _build_deno_lockfile(record)
        (tmpdir_path / "deno.lock").write_text(lockfile_content)

        # Install with frozen lockfile — deno verifies all integrity hashes
        click.echo(f"Installing with integrity verification ({len(resolved)} packages)...")
        subprocess.run(
            ["deno", "install", "--frozen"],
            cwd=tmpdir_path,
            check=True,
        )
        click.echo(f"Verified and installed {len(resolved)} packages")

        # Install globally from verified cache
        # (can't use --frozen here as global install creates a separate context)
        subprocess.run(
            ["deno", "install", "-g", *flags, pkg_spec, *extra_args],
            cwd=tmpdir_path,
            check=True,
        )
    return None


def extract_dist_metadata(url: str) -> dict:
    """Extract standardized metadata from a JSR or npm URL.

    Returns dict with optional keys: description, license, url.
    """
    if url.startswith("https://jsr.io/"):
        parts = url.rstrip("/").split("/")
        scope_name = "/".join(parts[3:5])
        meta_url = f"https://jsr.io/{scope_name}/meta.json"
        resp = httpx.get(meta_url, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        result: dict[str, str] = {}
        if "description" in data:
            result["description"] = data["description"]
        return result
    else:
        # npm tarball — delegate to node ecosystem
        from .node import extract_dist_metadata as node_extract
        return node_extract(url)


def format_resolve_output(resolved: list[dict]) -> str:
    """Format resolved deps for output."""
    return generate_requirements(resolved)
