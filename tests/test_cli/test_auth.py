"""Tests for auth CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestAuthSetToken:
    def test_set_token(self, runner, monkeypatch, tmp_path):
        from wealthbox.cli import config
        creds_file = tmp_path / ".config" / "wealthbox" / "credentials.json"
        monkeypatch.setattr(config, "get_credentials_path", lambda: creds_file)

        result = runner.invoke(cli, ["auth", "set-token", "my_new_token"])
        assert result.exit_code == 0
        assert "saved" in result.output.lower()
        data = json.loads(creds_file.read_text())
        assert data["access_token"] == "my_new_token"


class TestAuthTest:
    @responses.activate
    def test_auth_test_success(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}me",
            json={"current_user": {"id": 1, "name": "Test User"}},
            status=200,
        )
        result = runner.invoke(cli, ["auth", "test"])
        assert result.exit_code == 0
        assert "Test User" in result.output


class TestAuthWhoami:
    @responses.activate
    def test_whoami(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}me",
            json={"current_user": {"id": 1, "name": "Test User"}},
            status=200,
        )
        result = runner.invoke(cli, ["auth", "whoami", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["current_user"]["name"] == "Test User"


class TestNoAuth:
    def test_no_token_gives_auth_error(self, runner, monkeypatch, tmp_path):
        monkeypatch.delenv("WEALTHBOX_ACCESS_TOKEN", raising=False)
        monkeypatch.chdir(tmp_path)
        from wealthbox.cli import config
        monkeypatch.setattr(config, "get_credentials_path", lambda: tmp_path / "nope.json")

        result = runner.invoke(cli, ["contacts", "list", "--json"])
        assert result.exit_code != 0
