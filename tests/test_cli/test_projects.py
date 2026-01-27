"""Tests for project CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestProjectsList:
    @responses.activate
    def test_list_projects(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}projects",
            json={
                "projects": [{"id": 1, "name": "Project Alpha"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["projects", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1


class TestProjectsGet:
    @responses.activate
    def test_get_project(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}projects/7",
            json={"id": 7, "name": "Project Beta"},
            status=200,
        )
        result = runner.invoke(cli, ["projects", "get", "7", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["name"] == "Project Beta"


class TestProjectsCreate:
    @responses.activate
    def test_create_project(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}projects",
            json={"id": 20, "name": "New Project"},
            status=201,
        )
        result = runner.invoke(
            cli,
            ["projects", "create", "--name", "New Project", "--json"],
        )
        assert result.exit_code == 0


class TestProjectsUpdate:
    @responses.activate
    def test_update_project(self, runner, mock_token):
        responses.add(
            responses.PUT,
            f"{BASE_URL}projects/7",
            json={"id": 7, "name": "Renamed"},
            status=200,
        )
        result = runner.invoke(
            cli,
            ["projects", "update", "7", "--name", "Renamed", "--json"],
        )
        assert result.exit_code == 0


class TestProjectsDelete:
    @responses.activate
    def test_delete_project(self, runner, mock_token):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}projects/7",
            status=204,
        )
        result = runner.invoke(cli, ["projects", "delete", "7", "--confirm"])
        assert result.exit_code == 0
