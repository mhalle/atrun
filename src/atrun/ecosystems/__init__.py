"""Ecosystem registry and auto-detection.

Manages the mapping between ecosystem names (python, node, deno) and their
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
    "deno": ".deno",
}


def get_ecosystem(name: str) -> ModuleType:
    """Return the ecosystem module for the given name.

    Valid names: 'python', 'node', 'deno'.
    Raises SystemExit for unknown ecosystems.
    """
    rel = _ECOSYSTEM_MODULES.get(name)
    if rel is None:
        raise SystemExit(f"Unknown ecosystem: {name}")
    return importlib.import_module(rel, package=__name__)


def detect_ecosystem_from_record(record: dict) -> str:
    """Detect the ecosystem from a record's ecosystem.$type field.

    Matches the $type against each ecosystem module's ECOSYSTEM_TYPE constant.
    Falls back to 'python' if no match is found.
    """
    eco = record.get("ecosystem", {})
    eco_type = eco.get("$type", "")
    for name, mod_path in _ECOSYSTEM_MODULES.items():
        mod = importlib.import_module(mod_path, package=__name__)
        if eco_type == mod.ECOSYSTEM_TYPE:
            return name
    return "python"


def detect_ecosystem_from_url(url: str) -> str | None:
    """Auto-detect ecosystem from a distribution URL.

    Recognizes:
      - registry.npmjs.org -> 'node'
      - jsr.io -> 'deno'
      - files.pythonhosted.org or .whl extension -> 'python'

    Returns None if the URL doesn't match a known ecosystem.
    Note: npm URLs are mapped to 'node' by default. Use --ecosystem deno
    to override when publishing an npm package for the Deno ecosystem.
    """
    if "registry.npmjs.org" in url:
        return "node"
    if "jsr.io" in url:
        return "deno"
    if "files.pythonhosted.org" in url or url.endswith(".whl"):
        return "python"
    return None


def detect_ecosystem_from_lockfile(content: str) -> str:
    """Auto-detect ecosystem by inspecting lockfile content.

    Detection rules:
      - Valid TOML -> 'python' (pylock.toml)
      - JSON with 'lockfileVersion' -> 'node' (package-lock.json)
      - JSON with 'version' and npm/jsr package sections -> 'deno' (deno.lock)

    Raises SystemExit if the content cannot be identified.
    """
    # Try TOML first (Python pylock.toml)
    try:
        tomllib.loads(content)
        return "python"
    except Exception:
        pass

    # Try JSON (Node or Deno)
    try:
        data = json.loads(content)
    except Exception:
        raise SystemExit("Cannot detect ecosystem: lockfile is neither TOML nor JSON.")

    # Node: package-lock.json has lockfileVersion
    if "lockfileVersion" in data:
        return "node"

    # Deno: deno.lock has version + (packages.jsr/npm or top-level npm/jsr)
    if "version" in data:
        pkgs = data.get("packages", {})
        if isinstance(pkgs, dict) and ("jsr" in pkgs or "npm" in pkgs):
            return "deno"
        if "npm" in data or "jsr" in data:
            return "deno"

    raise SystemExit("Cannot detect ecosystem from lockfile content.")
