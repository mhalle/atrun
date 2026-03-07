"""Authentication and session management for AT Protocol."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx

SESSION_DIR = Path.home() / ".config" / "atrun"
SESSION_FILE = SESSION_DIR / "session.json"
SESSIONS_DIR = SESSION_DIR / "sessions"


def _session_file_for_handle(handle: str) -> Path:
    """Return the per-handle session file path.

    Normalizes the handle by stripping leading @ and lowercasing.
    """
    normalized = handle.strip().lstrip("@").lower()
    return SESSIONS_DIR / f"{normalized}.json"


def _save_session(session: dict, path: Path) -> None:
    """Write a session dict to a file with 600 permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def discover_project_handle() -> str | None:
    """Walk up from cwd looking for a project config with an atpub handle.

    Checks pyproject.toml, package.json, and Cargo.toml in each directory.
    Stops at a .git directory boundary.
    """
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        # pyproject.toml → [tool.atpub].handle
        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib  # type: ignore[no-redef]
            try:
                data = tomllib.loads(pyproject.read_text())
                handle = data.get("tool", {}).get("atpub", {}).get("handle")
                if handle:
                    return handle.strip().lstrip("@")
            except Exception:
                pass

        # package.json → "atpub": {"handle": "..."}
        pkg_json = directory / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
                handle = data.get("atpub", {}).get("handle")
                if handle:
                    return handle.strip().lstrip("@")
            except Exception:
                pass

        # Cargo.toml → [package.metadata.atpub].handle
        cargo = directory / "Cargo.toml"
        if cargo.exists():
            try:
                import tomllib
            except ModuleNotFoundError:
                import tomli as tomllib  # type: ignore[no-redef]
            try:
                data = tomllib.loads(cargo.read_text())
                handle = data.get("package", {}).get("metadata", {}).get("atpub", {}).get("handle")
                if handle:
                    return handle.strip().lstrip("@")
            except Exception:
                pass

        # Stop at .git boundary
        if (directory / ".git").exists():
            break

    return None


def login(handle: str, app_password: str) -> dict:
    """Create a session via com.atproto.server.createSession.

    Returns the session dict and saves it to both the per-handle file
    and the legacy default file.
    """
    handle = handle.strip().lstrip("@")
    app_password = app_password.strip()

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

    # Save to per-handle file
    _save_session(session, _session_file_for_handle(handle))

    # Save to legacy default file (last login = default)
    _save_session(session, SESSION_FILE)

    return session


def load_session(handle: str | None = None) -> dict:
    """Load a saved session following the resolution chain.

    Resolution order:
    1. ATRUN_SESSION env var (pre-built session JSON)
    2. ATRUN_HANDLE + ATRUN_APP_PASSWORD env vars (fresh login, for CI/CD)
    3. handle argument → per-handle session file
    4. Project config discovery (pyproject.toml, package.json, Cargo.toml)
    5. Legacy session.json
    """
    env_session = os.environ.get("ATRUN_SESSION")
    if env_session:
        return json.loads(env_session)

    # CI/CD: fresh login from env vars
    env_handle = os.environ.get("ATRUN_HANDLE")
    env_password = os.environ.get("ATRUN_APP_PASSWORD")
    if env_handle and env_password:
        return login(env_handle, env_password)

    # Explicit handle argument
    if handle:
        path = _session_file_for_handle(handle)
        if path.exists():
            return json.loads(path.read_text())
        # Fall through to legacy if per-handle file doesn't exist
        if SESSION_FILE.exists():
            return json.loads(SESSION_FILE.read_text())
        raise SystemExit(f"No session found for {handle}. Run `atrun login --handle {handle}` first.")

    # Project config discovery
    project_handle = discover_project_handle()
    if project_handle:
        path = _session_file_for_handle(project_handle)
        if path.exists():
            return json.loads(path.read_text())

    # Legacy fallback
    if not SESSION_FILE.exists():
        raise SystemExit("No session found. Run `atrun login` first.")

    return json.loads(SESSION_FILE.read_text())


def refresh_session(session: dict, handle: str | None = None) -> dict:
    """Refresh an expired session using the refresh token.

    Writes the refreshed session back to the correct per-handle file
    and the legacy file if appropriate.
    """
    resp = httpx.post(
        "https://bsky.social/xrpc/com.atproto.server.refreshSession",
        headers={"Authorization": f"Bearer {session['refreshJwt']}"},
    )
    resp.raise_for_status()
    new_session = resp.json()

    # Determine the handle to save under
    effective_handle = handle or new_session.get("handle")
    if effective_handle:
        _save_session(new_session, _session_file_for_handle(effective_handle))

    # Always update legacy file
    _save_session(new_session, SESSION_FILE)

    return new_session
