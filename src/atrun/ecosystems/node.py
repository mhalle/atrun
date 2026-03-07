"""Node.js (npm) ecosystem support."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

import httpx

LOCKFILE_EXTENSIONS = [".json"]


def _hex_to_sri(hash_str: str) -> str:
    """Convert algo:hex format back to SRI (algo-base64)."""
    algo, hex_hash = hash_str.split(":", 1)
    raw = bytes.fromhex(hex_hash)
    b64 = base64.b64encode(raw).decode()
    return f"{algo}-{b64}"


def _verify_hash(data: bytes, expected_hash: str) -> bool:
    """Verify data against an algo:hex hash."""
    algo, expected_hex = expected_hash.split(":", 1)
    h = hashlib.new(algo)
    h.update(data)
    return h.hexdigest() == expected_hex


def _convert_sri_hash(sri: str) -> str:
    """Convert SRI hash (sha512-base64) to algo:hex format."""
    # Already in algo:hex format
    if ":" in sri:
        return sri
    # SRI format: algo-base64
    if "-" not in sri:
        return sri
    algo, b64 = sri.split("-", 1)
    hex_hash = base64.b64decode(b64).hex()
    return f"{algo}:{hex_hash}"


def parse_lockfile(content: str) -> list[dict]:
    """Parse package-lock.json v3 and return sorted dependency entries."""
    data = json.loads(content)
    packages = data.get("packages", {})

    # First pass: build a map of name -> [(version, key, info)] for dep resolution
    # For nested node_modules, a package resolves deps by walking up the tree
    pkg_versions: dict[str, list[tuple[str, str]]] = {}
    for key, info in packages.items():
        if not key or "node_modules/" not in key:
            continue
        last_nm = key.rfind("node_modules/")
        name = key[last_nm + len("node_modules/"):]
        version = info.get("version")
        if version:
            pkg_versions.setdefault(name, []).append((version, key))

    def _resolve_dep_version(dep_name: str, parent_key: str) -> str | None:
        """Resolve a dependency name to its exact installed version.

        Walks up from the parent's node_modules to find the nearest match,
        mimicking Node.js resolution. Falls back to first available version.
        """
        candidates = pkg_versions.get(dep_name, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][0]

        # Check for nested version: parent_key/node_modules/dep_name
        nested_key = f"{parent_key}/node_modules/{dep_name}"
        for version, key in candidates:
            if key == nested_key:
                return version

        # Fall back to top-level node_modules/dep_name
        top_key = f"node_modules/{dep_name}"
        for version, key in candidates:
            if key == top_key:
                return version

        return candidates[0][0]

    # Second pass: build entries with resolved dependencies
    seen = {}
    entries = []
    for key, info in packages.items():
        if not key or "node_modules/" not in key:
            continue

        last_nm = key.rfind("node_modules/")
        name = key[last_nm + len("node_modules/"):]
        version = info.get("version")
        if not version:
            continue

        integrity = info.get("integrity", "")
        hash_str = _convert_sri_hash(integrity) if integrity else ""

        resolved_url = info.get("resolved", "")
        if not resolved_url:
            pkg_basename = name.split("/")[-1]
            resolved_url = f"https://registry.npmjs.org/{name}/-/{pkg_basename}-{version}.tgz"

        if hash_str:
            dedup_key = (name, version)
            if dedup_key not in seen:
                seen[dedup_key] = True

                # Resolve dependencies to exact versions
                deps = []
                raw_deps = info.get("dependencies", {})
                for dep_name in sorted(raw_deps):
                    dep_version = _resolve_dep_version(dep_name, key)
                    if dep_version:
                        deps.append(f"{dep_name}@{dep_version}")

                entry = {
                    "name": name,
                    "version": version,
                    "hash": hash_str,
                    "url": resolved_url,
                }
                if deps:
                    entry["dependencies"] = deps
                entries.append(entry)

    entries.sort(key=lambda e: e["name"])
    return entries


def export_lockfile() -> str:
    """Read ./package-lock.json and return its content."""
    from pathlib import Path
    lock_path = Path("package-lock.json")
    if not lock_path.exists():
        raise SystemExit("package-lock.json not found in current directory.")
    return lock_path.read_text()


def build_metadata() -> dict:
    """Return ecosystem-specific metadata for the manifest.

    Includes the Node.js runtime engine.
    """
    return {"engine": "node"}


def generate_requirements(resolved: list[dict]) -> str:
    """Format resolved deps as package specs."""
    lines = []
    for entry in resolved:
        lines.append(f"{entry['name']}@{entry['version']}")
    return "\n".join(lines)


SUPPORTED_ENGINES = ("pnpm", "bun", "npm")
DEFAULT_ENGINE = "pnpm"


def _check_pnpm_global_bin():
    """Check that pnpm global bin directory is configured and in PATH."""
    import os
    result = subprocess.run(
        ["pnpm", "config", "get", "global-bin-dir"],
        capture_output=True, text=True,
    )
    bin_dir = result.stdout.strip() if result.returncode == 0 else ""
    if not bin_dir or bin_dir == "undefined":
        raise SystemExit(
            "pnpm global bin directory is not configured.\n"
            "Run 'pnpm setup' then restart your shell, or set it manually:\n"
            "  pnpm config set global-bin-dir ~/Library/pnpm\n"
            "  export PNPM_HOME=~/Library/pnpm\n"
            "  export PATH=\"$PNPM_HOME:$PATH\""
        )
    if bin_dir not in os.environ.get("PATH", ""):
        raise SystemExit(
            f"pnpm global bin directory ({bin_dir}) is not in PATH.\n"
            "Add to your shell profile:\n"
            f"  export PATH=\"{bin_dir}:$PATH\""
        )


def _check_engine(engine: str):
    """Validate engine and check prerequisites."""
    if engine not in SUPPORTED_ENGINES:
        raise SystemExit(f"Unknown engine: {engine}. Supported: {', '.join(SUPPORTED_ENGINES)}")
    if engine == "pnpm":
        _check_pnpm_global_bin()


def generate_install_args(record: dict, engine: str = DEFAULT_ENGINE) -> list[str]:
    """Build global install command args for the chosen engine."""
    _check_engine(engine)
    package = record.get("package")
    resolved = record.get("resolved", [])

    pkg_entry = next((e for e in resolved if e["name"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in resolved list.")

    version = pkg_entry["version"]
    return [engine, "install", "-g", f"{package}@{version}"]


def generate_run_args(record: dict, engine: str = DEFAULT_ENGINE) -> list[str]:
    """Build args for running a Node.js package."""
    package = record.get("package")
    if engine == "bun":
        return ["bunx", package]
    elif engine == "npm":
        return ["npx", package]
    return ["pnpm", "exec", package]


def fetch_metadata(url: str) -> dict:
    """Fetch metadata from an npm tarball URL."""
    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()

    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
        # package.json is usually at package/package.json
        pkg_json_path = next(
            (m.name for m in tf.getmembers() if m.name.endswith("/package.json")),
            None,
        )
        if not pkg_json_path:
            raise ValueError(f"No package.json found in tarball at {url}")

        f = tf.extractfile(pkg_json_path)
        if f is None:
            raise ValueError(f"Cannot read {pkg_json_path} from tarball")
        data = json.loads(f.read())

    result: dict[str, str | list[str]] = {}
    for field in ("name", "version", "description", "author", "license", "homepage"):
        if field in data:
            val = data[field]
            if isinstance(val, dict):
                val = val.get("name", str(val))
            result[field.capitalize()] = val

    if "keywords" in data:
        result["Keywords"] = data["keywords"]

    deps = data.get("dependencies", {})
    if deps:
        result["Dependencies"] = [f"{k}@{v}" for k, v in deps.items()]

    return result


def _build_pnpm_lockfile(record: dict) -> str:
    """Reconstruct a pnpm-lock.yaml from the record's resolved entries."""
    import yaml

    package = record["package"]
    resolved = record["resolved"]

    pkg_entry = next(e for e in resolved if e["name"] == package)
    version = pkg_entry["version"]

    # Build packages section (integrity) and snapshots section (deps)
    packages = {}
    snapshots = {}

    for entry in resolved:
        key = f"{entry['name']}@{entry['version']}"
        sri = _hex_to_sri(entry["hash"])

        pkg_info: dict = {"resolution": {"integrity": sri}}
        if entry["name"] == package:
            pkg_info["hasBin"] = True
        packages[key] = pkg_info

        # Snapshots: dependency relationships
        deps = entry.get("dependencies", [])
        if deps:
            snap_deps = {}
            for dep_str in deps:
                at_idx = dep_str.rfind("@", 1)
                dep_name = dep_str[:at_idx]
                dep_ver = dep_str[at_idx + 1:]
                snap_deps[dep_name] = dep_ver
            snapshots[key] = {"dependencies": snap_deps}
        else:
            snapshots[key] = {}

    lock = {
        "lockfileVersion": "9.0",
        "settings": {
            "autoInstallPeers": True,
            "excludeLinksFromLockfile": False,
        },
        "importers": {
            ".": {
                "dependencies": {
                    package: {
                        "specifier": version,
                        "version": version,
                    },
                },
            },
        },
        "packages": packages,
        "snapshots": snapshots,
    }

    return yaml.dump(lock, default_flow_style=False, sort_keys=False)


def run_verified_install(record: dict, extra_args: tuple[str, ...] = (), dry_run: bool = False, engine: str = DEFAULT_ENGINE) -> list[str] | None:
    """Install with a reconstructed lockfile and frozen lockfile verification.

    For pnpm: reconstructs pnpm-lock.yaml, verifies with --frozen-lockfile.
    For bun/npm: uses --frozen-lockfile for verification.
    Then installs globally using the chosen engine.
    """
    import click

    package = record.get("package")
    resolved = record.get("resolved", [])

    pkg_entry = next((e for e in resolved if e["name"] == package), None)
    if not pkg_entry:
        raise SystemExit(f"Package '{package}' not found in resolved list.")
    version = pkg_entry["version"]

    # Check if record has dependency info for frozen lockfile install
    has_deps = any(e.get("dependencies") for e in resolved)

    if not has_deps:
        # Fallback: direct install without lockfile verification
        cmd = [engine, "install", "-g", f"{package}@{version}", *extra_args]
        if dry_run:
            return cmd
        _check_engine(engine)
        click.echo("No dependency graph in record — installing without lockfile verification")
        subprocess.run(cmd, check=True)
        return None

    if dry_run:
        return [engine, "install", "--frozen-lockfile", f"{package}@{version}", *extra_args]

    # Verified install currently requires pnpm (reconstructs pnpm-lock.yaml)
    if engine != "pnpm":
        click.echo(f"Verified install with --deps requires pnpm (using pnpm for verification, {engine} for global install)")

    with tempfile.TemporaryDirectory(prefix="atrun-node-") as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write package.json
        pkg_json = {
            "name": "atrun-install",
            "version": "0.0.0",
            "dependencies": {package: version},
        }
        (tmpdir_path / "package.json").write_text(json.dumps(pkg_json))

        # Write reconstructed pnpm-lock.yaml
        lockfile_content = _build_pnpm_lockfile(record)
        (tmpdir_path / "pnpm-lock.yaml").write_text(lockfile_content)

        # Install with frozen lockfile — pnpm verifies all integrity hashes
        click.echo(f"Installing with integrity verification ({len(resolved)} packages)...")
        subprocess.run(
            ["pnpm", "install", "--frozen-lockfile"],
            cwd=tmpdir_path,
            check=True,
        )
        click.echo(f"Verified and installed {len(resolved)} packages")

        # Install globally using chosen engine
        _check_engine(engine)
        subprocess.run(
            [engine, "install", "-g", f"{package}@{version}", *extra_args],
            check=True,
        )
    return None


def extract_dist_metadata(url: str) -> dict:
    """Extract standardized metadata from an npm tarball URL.

    Returns dict with optional keys: description, license, url.
    """
    import io
    import tarfile

    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()

    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
        pkg_json_path = next(
            (m.name for m in tf.getmembers() if m.name.endswith("/package.json")),
            None,
        )
        if not pkg_json_path:
            return {}
        f = tf.extractfile(pkg_json_path)
        if f is None:
            return {}
        data = json.loads(f.read())

    result: dict[str, str] = {}
    if "description" in data:
        result["description"] = data["description"]
    if "license" in data:
        result["license"] = data["license"]
    if "homepage" in data:
        result["url"] = data["homepage"]
    elif "repository" in data:
        repo = data["repository"]
        if isinstance(repo, dict):
            repo = repo.get("url", "")
        if isinstance(repo, str) and repo:
            # Normalize git+https:// URLs
            repo = repo.removeprefix("git+").removesuffix(".git")
            if repo.startswith("http"):
                result["url"] = repo

    return result


def format_resolve_output(resolved: list[dict]) -> str:
    """Format resolved deps for output."""
    return generate_requirements(resolved)
