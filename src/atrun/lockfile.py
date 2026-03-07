"""Parse pylock.toml into resolved dependency entries.

Thin wrapper around ecosystems.python for backwards compatibility.
"""

from __future__ import annotations

from .ecosystems.python import export_lockfile as export_pylock
from .ecosystems.python import parse_lockfile as parse_pylock

__all__ = ["export_pylock", "parse_pylock"]
