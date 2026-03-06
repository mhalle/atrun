"""Authentication and session management for AT Protocol."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx

SESSION_DIR = Path.home() / ".config" / "atrun"
SESSION_FILE = SESSION_DIR / "session.json"


def login(handle: str, app_password: str) -> dict:
    """Create a session via com.atproto.server.createSession.

    Returns the session dict and saves it to disk.
    """
    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": app_password},
    )
    if resp.status_code == 401:
        raise SystemExit(
            "Login failed: invalid handle or password.\n"
            "Make sure you're using an App Password (Settings → App Passwords in Bluesky)."
        )
    resp.raise_for_status()
    session = resp.json()

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(session))
    SESSION_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600

    return session


def load_session() -> dict:
    """Load a saved session from disk or ATRUN_SESSION env var."""
    env_session = os.environ.get("ATRUN_SESSION")
    if env_session:
        return json.loads(env_session)

    if not SESSION_FILE.exists():
        raise SystemExit("No session found. Run `atrun login` first.")

    return json.loads(SESSION_FILE.read_text())


def refresh_session(session: dict) -> dict:
    """Refresh an expired session using the refresh token."""
    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.server.refreshSession",
        headers={"Authorization": f"Bearer {session['refreshJwt']}"},
    )
    resp.raise_for_status()
    new_session = resp.json()

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(new_session))
    SESSION_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)

    return new_session
