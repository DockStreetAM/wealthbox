"""Tests for CLI config/token loading."""

import json
import os
import tempfile

import pytest

from wealthbox.cli.config import load_token, save_token, _parse_env_file


class TestLoadToken:
    def test_from_env_var(self, monkeypatch):
        monkeypatch.setenv("WEALTHBOX_ACCESS_TOKEN", "env_token_123")
        assert load_token() == "env_token_123"

    def test_env_var_takes_precedence(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WEALTHBOX_ACCESS_TOKEN", "env_token")
        # Create a .env file too
        env_file = tmp_path / ".env"
        env_file.write_text("WEALTHBOX_ACCESS_TOKEN=dotenv_token")
        monkeypatch.chdir(tmp_path)
        assert load_token() == "env_token"

    def test_cwd_dotenv_not_loaded(self, monkeypatch, tmp_path):
        """A .env in CWD must not supply (or override) the token.

        Replaces the old test_from_dotenv_file, which asserted the CWD .env
        WAS loaded — a cloned repo's .env could silently swap workspaces.
        """
        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        (tmp_path / ".env").write_text("WEALTHBOX_ACCESS_TOKEN=attacker_token")
        monkeypatch.chdir(tmp_path)
        creds_file = tmp_path / "creds" / "credentials.json"
        creds_file.parent.mkdir()
        creds_file.write_text(json.dumps({"access_token": "stored_token"}))
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds_file)
        assert load_token() == "stored_token"

    def test_explicit_env_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        env_file = tmp_path / "my.env"
        env_file.write_text("WEALTHBOX_ACCESS_TOKEN=dotenv_token_456")
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: tmp_path / "nope" / "credentials.json")
        assert load_token(env_file=env_file) == "dotenv_token_456"

    def test_config_dir_env_below_credentials(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / ".env").write_text("WEALTHBOX_ACCESS_TOKEN=cfg_env_token")
        creds_file = cfg / "credentials.json"
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds_file)
        # No credentials file yet: config-dir .env is used
        assert load_token() == "cfg_env_token"
        # Credentials file wins once present
        creds_file.write_text(json.dumps({"access_token": "stored_token"}))
        assert load_token() == "stored_token"

    def test_env_file_cli_option(self, monkeypatch, tmp_path):
        """wb --env-file PATH feeds the token to the client."""
        import responses as rsps
        from click.testing import CliRunner
        from wealthbox.cli.main import cli

        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: tmp_path / "nope" / "credentials.json")
        env_file = tmp_path / "x.env"
        env_file.write_text("WEALTHBOX_ACCESS_TOKEN=from_env_file")
        with rsps.RequestsMock() as mock:
            mock.add(rsps.GET, "https://api.crmworkspace.com/v1/me",
                     json={"current_user": {"name": "U"}}, status=200)
            result = CliRunner().invoke(cli, ["--env-file", str(env_file), "auth", "test"])
            assert result.exit_code == 0, result.output
            assert mock.calls[0].request.headers["ACCESS_TOKEN"] == "from_env_file"

    def test_from_credentials_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        # No .env in cwd
        monkeypatch.chdir(tmp_path)

        creds_dir = tmp_path / ".config" / "wealthbox"
        creds_dir.mkdir(parents=True)
        creds_file = creds_dir / "credentials.json"
        creds_file.write_text(json.dumps({"access_token": "creds_token_789"}))

        # Monkey-patch the credentials path
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds_file)

        assert load_token() == "creds_token_789"

    def test_returns_none_when_no_token(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        monkeypatch.chdir(tmp_path)
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: tmp_path / "nonexistent.json")
        assert load_token() is None


class TestSaveToken:
    def test_saves_and_loads(self, monkeypatch, tmp_path):
        creds_file = tmp_path / ".config" / "wealthbox" / "credentials.json"
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds_file)

        save_token("saved_token_abc")
        assert creds_file.exists()
        data = json.loads(creds_file.read_text())
        assert data["access_token"] == "saved_token_abc"


class TestParseEnvFile:
    def test_parses_simple(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("WEALTHBOX_ACCESS_TOKEN=my_token\n")
        assert _parse_env_file(env_file) == "my_token"

    def test_parses_quoted(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('WEALTHBOX_ACCESS_TOKEN="quoted_token"\n')
        assert _parse_env_file(env_file) == "quoted_token"

    def test_ignores_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nWEALTHBOX_ACCESS_TOKEN=my_token\n")
        assert _parse_env_file(env_file) == "my_token"

    def test_returns_none_for_missing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("OTHER_VAR=value\n")
        assert _parse_env_file(env_file) is None

    def test_returns_none_for_missing_file(self, tmp_path):
        assert _parse_env_file(tmp_path / "nonexistent") is None
