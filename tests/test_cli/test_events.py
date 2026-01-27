"""Tests for event CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestEventsList:
    @responses.activate
    def test_list_events(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}events",
            json={
                "events": [{"id": 1, "name": "Meeting"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["events", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1


class TestEventsGet:
    @responses.activate
    def test_get_event(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}events/10",
            json={"id": 10, "name": "Annual review"},
            status=200,
        )
        result = runner.invoke(cli, ["events", "get", "10", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["id"] == 10


class TestEventsCreate:
    @responses.activate
    def test_create_event(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}events",
            json={"id": 20, "name": "New meeting"},
            status=201,
        )
        result = runner.invoke(
            cli,
            [
                "events", "create",
                "--name", "New meeting",
                "--start", "2026-02-01T09:00:00",
                "--json",
            ],
        )
        assert result.exit_code == 0


class TestEventsDelete:
    @responses.activate
    def test_delete_event(self, runner, mock_token):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}events/10",
            status=204,
        )
        result = runner.invoke(cli, ["events", "delete", "10", "--confirm"])
        assert result.exit_code == 0
