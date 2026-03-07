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
}


def get_ecosystem(name: str) -> ModuleType:
    """Return the ecosystem module for the given name.

    Valid names: 'python', 'node'.
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
      - files.pythonhosted.org or .whl extension -> 'python'

    Returns None if the URL doesn't match a known ecosystem.
    """
    if "registry.npmjs.org" in url:
        return "node"
    if "files.pythonhosted.org" in url or url.endswith(".whl"):
        return "python"
    return None


def detect_ecosystem_from_lockfile(content: str) -> str:
    """Auto-detect ecosystem by inspecting lockfile content.

    Detection rules:
      - Valid TOML -> 'python' (pylock.toml)
      - JSON with 'lockfileVersion' -> 'node' (package-lock.json)

    Raises SystemExit if the content cannot be identified.
    """
    # Try TOML first (Python pylock.toml)
    try:
        tomllib.loads(content)
        return "python"
    except Exception:
        pass

    # Try JSON (Node)
    try:
        data = json.loads(content)
    except Exception:
        raise SystemExit("Cannot detect ecosystem: lockfile is neither TOML nor JSON.")

    if "lockfileVersion" in data:
        return "node"

    raise SystemExit("Cannot detect ecosystem from lockfile content.")
