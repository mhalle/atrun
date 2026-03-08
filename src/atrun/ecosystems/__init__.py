"""Ecosystem registry and auto-detection.

Manages the mapping between ecosystem names (python, node) and their
implementation modules. Provides auto-detection from lockfile content,
dist URLs, and AT Protocol record types.
"""

from __future__ import annotations

import importlib
import json
import tomllib
from types import ModuleType


_ECOSYSTEM_MODULES = {
    "python": ".python",
    "node": ".node",
    "rust": ".rust",
    "go": ".go",
    "container": ".container",
}

PACKAGE_TYPES = {
    "python": "dev.atpub.defs#pythonPackage",
    "node": "dev.atpub.defs#npmPackage",
    "rust": "dev.atpub.defs#rustCrate",
    "go": "dev.atpub.defs#goModule",
    "container": "dev.atpub.defs#container",
}

PACKAGE_TYPE_TO_ECOSYSTEM = {v: k for k, v in PACKAGE_TYPES.items()}


def get_ecosystem(name: str) -> ModuleType:
    """Return the ecosystem module for the given name.

    Valid names: 'python', 'node', 'rust', 'go', 'container'.
    Raises SystemExit for unknown ecosystems.
    """
    rel = _ECOSYSTEM_MODULES.get(name)
    if rel is None:
        raise SystemExit(f"Unknown ecosystem: {name}")
    return importlib.import_module(rel, package=__name__)


def detect_ecosystem_from_artifacts(artifacts: list[dict], record: dict | None = None) -> str:
    """Detect the ecosystem from a record's packageType or URL patterns.

    If a record with a packageType is provided, looks it up first.
    Otherwise checks the first artifacts entry's URL against known patterns:
      - crates.io -> 'rust'
      - registry.npmjs.org -> 'node'
      - .whl or files.pythonhosted.org -> 'python'

    Falls back to 'python' if no pattern matches.
    """
    if record is not None:
        pkg_type = record.get("packageType")
        if pkg_type:
            eco = PACKAGE_TYPE_TO_ECOSYSTEM.get(pkg_type)
            if eco:
                return eco
    if not artifacts:
        return "python"
    urls = artifacts[0].get("urls", [])
    url = urls[0] if urls else ""
    return detect_ecosystem_from_url(url) or "python"


def detect_ecosystem_from_url(url: str) -> str | None:
    """Auto-detect ecosystem from a distribution URL or purl.

    Recognizes:
      - pkg:pypi/… or pypi:… -> 'python'
      - pkg:npm/… or npm:… -> 'node'
      - pkg:cargo/… or crate:… -> 'rust'
      - pkg:golang/… or go:… -> 'go'
      - pkg:docker/… or pkg:oci/… or docker:… -> 'container'
      - registry.npmjs.org -> 'node'
      - files.pythonhosted.org or .whl extension -> 'python'

    Returns None if the URL doesn't match a known ecosystem.
    """
    if url.startswith("pkg:"):
        from ..purl import detect_ecosystem
        return detect_ecosystem(url)
    if "registry.npmjs.org" in url:
        return "node"
    if "files.pythonhosted.org" in url or url.endswith(".whl"):
        return "python"
    if "crates.io" in url:
        return "rust"
    if "proxy.golang.org" in url:
        return "go"
    if url.startswith("oci://"):
        return "container"
    return None


def detect_ecosystem_from_lockfile(content: str) -> str:
    """Auto-detect ecosystem by inspecting lockfile content.

    Detection rules:
      - TOML with [[package]] and checksum fields -> 'rust' (Cargo.lock)
      - TOML with [[packages]] or lock-version -> 'python' (pylock.toml)
      - JSON with 'lockfileVersion' -> 'node' (package-lock.json)

    Raises SystemExit if the content cannot be identified.
    """
    # Try YAML (compose file) — check for services key with image values
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict) and "services" in data:
            services = data["services"]
            if isinstance(services, dict) and any(
                isinstance(s, dict) and "image" in s for s in services.values()
            ):
                return "container"
    except Exception:
        pass

    # Try TOML first
    try:
        data = tomllib.loads(content)
        # Cargo.lock has [[package]] with checksum fields
        if "package" in data and isinstance(data["package"], list):
            if any(p.get("checksum") for p in data["package"]):
                return "rust"
        # pylock.toml has [[packages]] (plural) or lock-version
        return "python"
    except Exception:
        pass

    # Try JSON (Node)
    try:
        data = json.loads(content)
    except Exception:
        # Check for go.sum format: lines of "module version h1:hash"
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        if lines and all(l.split()[2].startswith("h1:") for l in lines if len(l.split()) == 3):
            return "go"
        raise SystemExit("Cannot detect ecosystem: unrecognized lockfile format.")

    if "lockfileVersion" in data:
        return "node"

    raise SystemExit("Cannot detect ecosystem from lockfile content.")


def detect_ecosystem_from_lockfile_path(path: str) -> str | None:
    """Auto-detect ecosystem from lockfile filename.

    Recognizes:
      - Cargo.lock -> 'rust'

    Returns None if not recognized (falls through to content detection).
    """
    if path.endswith("Cargo.lock"):
        return "rust"
    if path.endswith("go.sum"):
        return "go"
    basename = path.rsplit("/", 1)[-1] if "/" in path else path
    if basename in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"):
        return "container"
    if path.endswith(".images"):
        return "container"
    return None
