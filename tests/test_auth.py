"""Tests for atrun.auth — session management and project config discovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from atrun.auth import (
    _session_file_for_handle,
    discover_project_handle,
    load_session,
    login,
)


class TestSessionFileForHandle:
    def test_basic(self):
        path = _session_file_for_handle("alice.bsky.social")
        assert path.name == "alice.bsky.social.json"
        assert path.parent.name == "sessions"

    def test_strips_at(self):
        path = _session_file_for_handle("@alice.bsky.social")
        assert path.name == "alice.bsky.social.json"

    def test_lowercases(self):
        path = _session_file_for_handle("Alice.Bsky.Social")
        assert path.name == "alice.bsky.social.json"

    def test_strips_whitespace(self):
        path = _session_file_for_handle("  @Alice.Bsky.Social  ")
        assert path.name == "alice.bsky.social.json"


class TestDiscoverProjectHandle:
    def test_pyproject_toml(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[tool.atpub]\nhandle = "alice.bsky.social"\n'
        )
        monkeypatch.chdir(tmp_path)
        assert discover_project_handle() == "alice.bsky.social"

    def test_pyproject_toml_with_at(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[tool.atpub]\nhandle = "@alice.bsky.social"\n'
        )
        monkeypatch.chdir(tmp_path)
        assert discover_project_handle() == "alice.bsky.social"

    def test_package_json(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "myapp", "atpub": {"handle": "bob.bsky.social"}})
        )
        monkeypatch.chdir(tmp_path)
        assert discover_project_handle() == "bob.bsky.social"

    def test_cargo_toml(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / "Cargo.toml").write_text(
            '[package.metadata.atpub]\nhandle = "carol.bsky.social"\n'
        )
        monkeypatch.chdir(tmp_path)
        assert discover_project_handle() == "carol.bsky.social"

    def test_walks_up_to_parent(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[tool.atpub]\nhandle = "alice.bsky.social"\n'
        )
        subdir = tmp_path / "src" / "pkg"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        assert discover_project_handle() == "alice.bsky.social"

    def test_stops_at_git_boundary(self, tmp_path, monkeypatch):
        # Put config above .git — should not find it
        (tmp_path / "pyproject.toml").write_text(
            '[tool.atpub]\nhandle = "alice.bsky.social"\n'
        )
        subdir = tmp_path / "repo"
        subdir.mkdir()
        (subdir / ".git").mkdir()
        monkeypatch.chdir(subdir)
        assert discover_project_handle() is None

    def test_no_config(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)
        assert discover_project_handle() is None


class TestLoadSession:
    def test_env_var_takes_precedence(self, tmp_path, monkeypatch):
        session = {"did": "did:plc:env", "handle": "env.bsky.social", "accessJwt": "x", "refreshJwt": "y"}
        monkeypatch.setenv("ATRUN_SESSION", json.dumps(session))
        result = load_session(handle="other.bsky.social")
        assert result["did"] == "did:plc:env"

    @patch("atrun.auth.httpx.post")
    def test_env_handle_and_password_triggers_login(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.delenv("ATRUN_SESSION", raising=False)
        monkeypatch.setenv("ATRUN_HANDLE", "ci.bsky.social")
        monkeypatch.setenv("ATRUN_APP_PASSWORD", "secret-app-pw")
        session_data = {"did": "did:plc:ci", "handle": "ci.bsky.social", "accessJwt": "a", "refreshJwt": "r"}
        mock_resp = type("R", (), {"status_code": 200, "json": lambda self: session_data, "raise_for_status": lambda self: None})()
        mock_post.return_value = mock_resp

        with patch("atrun.auth.SESSIONS_DIR", tmp_path / "sessions"), \
             patch("atrun.auth.SESSION_DIR", tmp_path), \
             patch("atrun.auth.SESSION_FILE", tmp_path / "session.json"):
            result = load_session()

        assert result["did"] == "did:plc:ci"
        mock_post.assert_called_once()
        call_json = mock_post.call_args[1]["json"]
        assert call_json["identifier"] == "ci.bsky.social"
        assert call_json["password"] == "secret-app-pw"

    @patch("atrun.auth.httpx.post")
    def test_env_handle_alone_does_not_trigger_login(self, mock_post, tmp_path, monkeypatch):
        monkeypatch.delenv("ATRUN_SESSION", raising=False)
        monkeypatch.delenv("ATRUN_APP_PASSWORD", raising=False)
        monkeypatch.setenv("ATRUN_HANDLE", "ci.bsky.social")
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        legacy = tmp_path / "session.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        session = {"did": "did:plc:legacy", "handle": "legacy.bsky.social", "accessJwt": "a", "refreshJwt": "r"}
        legacy.write_text(json.dumps(session))

        with patch("atrun.auth.SESSIONS_DIR", tmp_path / "sessions"), \
             patch("atrun.auth.SESSION_FILE", legacy):
            result = load_session()

        assert result["did"] == "did:plc:legacy"
        mock_post.assert_not_called()

    def test_handle_arg_uses_per_handle_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATRUN_SESSION", raising=False)
        monkeypatch.delenv("ATRUN_HANDLE", raising=False)
        monkeypatch.delenv("ATRUN_APP_PASSWORD", raising=False)
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)
        session = {"did": "did:plc:alice", "handle": "alice.bsky.social", "accessJwt": "a", "refreshJwt": "r"}
        (sessions_dir / "alice.bsky.social.json").write_text(json.dumps(session))

        with patch("atrun.auth.SESSIONS_DIR", sessions_dir), \
             patch("atrun.auth.SESSION_FILE", tmp_path / "session.json"):
            result = load_session(handle="alice.bsky.social")
            assert result["did"] == "did:plc:alice"

    def test_project_config_discovery(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATRUN_SESSION", raising=False)
        monkeypatch.delenv("ATRUN_HANDLE", raising=False)
        monkeypatch.delenv("ATRUN_APP_PASSWORD", raising=False)
        # Set up project config
        (tmp_path / ".git").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[tool.atpub]\nhandle = "project.bsky.social"\n'
        )
        monkeypatch.chdir(tmp_path)

        sessions_dir = tmp_path / "config" / "sessions"
        sessions_dir.mkdir(parents=True)
        session = {"did": "did:plc:proj", "handle": "project.bsky.social", "accessJwt": "a", "refreshJwt": "r"}
        (sessions_dir / "project.bsky.social.json").write_text(json.dumps(session))

        with patch("atrun.auth.SESSIONS_DIR", sessions_dir), \
             patch("atrun.auth.SESSION_FILE", tmp_path / "config" / "session.json"):
            result = load_session()
            assert result["did"] == "did:plc:proj"

    def test_legacy_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATRUN_SESSION", raising=False)
        monkeypatch.delenv("ATRUN_HANDLE", raising=False)
        monkeypatch.delenv("ATRUN_APP_PASSWORD", raising=False)
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        legacy = tmp_path / "config" / "session.json"
        legacy.parent.mkdir(parents=True)
        session = {"did": "did:plc:legacy", "handle": "legacy.bsky.social", "accessJwt": "a", "refreshJwt": "r"}
        legacy.write_text(json.dumps(session))

        with patch("atrun.auth.SESSIONS_DIR", tmp_path / "config" / "sessions"), \
             patch("atrun.auth.SESSION_FILE", legacy):
            result = load_session()
            assert result["did"] == "did:plc:legacy"

    def test_no_session_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ATRUN_SESSION", raising=False)
        monkeypatch.delenv("ATRUN_HANDLE", raising=False)
        monkeypatch.delenv("ATRUN_APP_PASSWORD", raising=False)
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        with patch("atrun.auth.SESSIONS_DIR", tmp_path / "config" / "sessions"), \
             patch("atrun.auth.SESSION_FILE", tmp_path / "config" / "session.json"):
            with pytest.raises(SystemExit, match="No session found"):
                load_session()


class TestLoginSavesBothFiles:
    @patch("atrun.auth.httpx.post")
    def test_login_saves_per_handle_and_legacy(self, mock_post, tmp_path):
        session_data = {"did": "did:plc:test", "handle": "test.bsky.social", "accessJwt": "a", "refreshJwt": "r"}
        mock_resp = type("R", (), {"status_code": 200, "json": lambda self: session_data, "raise_for_status": lambda self: None})()
        mock_post.return_value = mock_resp

        sessions_dir = tmp_path / "sessions"
        legacy = tmp_path / "session.json"

        with patch("atrun.auth.SESSIONS_DIR", sessions_dir), \
             patch("atrun.auth.SESSION_DIR", tmp_path), \
             patch("atrun.auth.SESSION_FILE", legacy):
            login("test.bsky.social", "password123")

        assert (sessions_dir / "test.bsky.social.json").exists()
        assert legacy.exists()
        assert json.loads((sessions_dir / "test.bsky.social.json").read_text()) == session_data
        assert json.loads(legacy.read_text()) == session_data
