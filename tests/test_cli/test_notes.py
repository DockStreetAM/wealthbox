"""Tests for note CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestNotesList:
    @responses.activate
    def test_list_notes(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [{"id": 1, "content": "Called client"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["notes", "list", "--contact", "12345", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1
        assert parsed[0]["content"] == "Called client"


class TestNotesGet:
    @responses.activate
    def test_get_note(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes/5",
            json={"id": 5, "content": "Meeting notes"},
            status=200,
        )
        result = runner.invoke(cli, ["notes", "get", "5", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["content"] == "Meeting notes"


class TestNotesCreate:
    @responses.activate
    def test_create_note(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}notes",
            json={"id": 10, "content": "New note"},
            status=201,
        )
        result = runner.invoke(
            cli,
            [
                "notes", "create",
                "--content", "New note",
                "--link-contact", "12345",
                "--json",
            ],
        )
        assert result.exit_code == 0
        body = json.loads(responses.calls[0].request.body)
        assert body["content"] == "New note"
        assert body["linked_to"] == [{"id": 12345, "type": "Contact"}]


class TestNotesUpdate:
    @responses.activate
    def test_update_note(self, runner, mock_token):
        responses.add(
            responses.PUT,
            f"{BASE_URL}notes/5",
            json={"id": 5, "content": "Updated note"},
            status=200,
        )
        result = runner.invoke(
            cli,
            ["notes", "update", "5", "--content", "Updated note", "--json"],
        )
        assert result.exit_code == 0
