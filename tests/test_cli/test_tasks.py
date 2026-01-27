"""Tests for task CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestTasksList:
    @responses.activate
    def test_list_tasks(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={
                "tasks": [
                    {"id": 1, "name": "Follow up", "completed": False},
                    {"id": 2, "name": "Review", "completed": True},
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["tasks", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 2


class TestTasksGet:
    @responses.activate
    def test_get_task(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks/42",
            json={"id": 42, "name": "Important task"},
            status=200,
        )
        result = runner.invoke(cli, ["tasks", "get", "42", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["id"] == 42


class TestTasksCreate:
    @responses.activate
    def test_create_task(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 100, "name": "New task"},
            status=201,
        )
        result = runner.invoke(
            cli, ["tasks", "create", "--name", "New task", "--json"]
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["name"] == "New task"

    @responses.activate
    def test_create_task_with_options(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 101, "name": "Follow up"},
            status=201,
        )
        result = runner.invoke(
            cli,
            [
                "tasks", "create",
                "--name", "Follow up",
                "--due-date", "2026-03-15",
                "--link-contact", "12345",
                "--description", "Call client",
                "--json",
            ],
        )
        assert result.exit_code == 0
        body = json.loads(responses.calls[0].request.body)
        assert body["name"] == "Follow up"
        assert body["due_date"] == "2026-03-15T00:00:00Z"
        assert body["linked_to"] == [{"id": 12345, "type": "Contact"}]
        assert body["description"] == "Call client"


class TestTasksUpdate:
    @responses.activate
    def test_update_task(self, runner, mock_token):
        responses.add(
            responses.PUT,
            f"{BASE_URL}tasks/42",
            json={"id": 42, "name": "Updated task"},
            status=200,
        )
        result = runner.invoke(
            cli, ["tasks", "update", "42", "--name", "Updated task", "--json"]
        )
        assert result.exit_code == 0


class TestTasksComplete:
    @responses.activate
    def test_complete_task(self, runner, mock_token):
        responses.add(
            responses.PUT,
            f"{BASE_URL}tasks/42",
            json={"id": 42, "completed": True},
            status=200,
        )
        result = runner.invoke(cli, ["tasks", "complete", "42", "--json"])
        assert result.exit_code == 0
        body = json.loads(responses.calls[0].request.body)
        assert body["completed"] is True


class TestTasksDelete:
    @responses.activate
    def test_delete_task(self, runner, mock_token):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}tasks/42",
            status=204,
        )
        result = runner.invoke(cli, ["tasks", "delete", "42", "--confirm"])
        assert result.exit_code == 0
        assert "deleted" in result.output
