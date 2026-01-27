"""Tests for contact CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestContactsList:
    @responses.activate
    def test_list_contacts_json(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [
                    {"id": 1, "name": "John Smith", "type": "Person"},
                    {"id": 2, "name": "Jane Doe", "type": "Person"},
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["contacts", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "John Smith"

    @responses.activate
    def test_list_contacts_count(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1}, {"id": 2}, {"id": 3}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["contacts", "list", "--count"])
        assert result.exit_code == 0
        assert result.output.strip() == "3"

    @responses.activate
    def test_list_contacts_head(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1}, {"id": 2}, {"id": 3}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["contacts", "list", "--head", "2", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 2

    @responses.activate
    def test_list_contacts_oneline(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["contacts", "list", "--oneline"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # Each line should be valid JSON

    @responses.activate
    def test_list_contacts_fields(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1, "name": "John", "email": "j@example.com"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["contacts", "list", "--json", "--fields", "id,name"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "email" not in parsed[0]
        assert "id" in parsed[0]


class TestContactsGet:
    @responses.activate
    def test_get_contact(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/12345",
            json={"id": 12345, "name": "John Smith", "type": "Person"},
            status=200,
        )
        result = runner.invoke(cli, ["contacts", "get", "12345", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["id"] == 12345
        assert parsed["name"] == "John Smith"


class TestContactsSearch:
    @responses.activate
    def test_search_contacts(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1, "name": "John Smith"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["contacts", "search", "John", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1


class TestContactsCreate:
    @responses.activate
    def test_create_contact(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}contacts",
            json={"id": 999, "first_name": "Test", "last_name": "User", "type": "Person"},
            status=201,
        )
        result = runner.invoke(
            cli,
            ["contacts", "create", "--first-name", "Test", "--last-name", "User", "--json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["id"] == 999

    @responses.activate
    def test_create_with_email_and_phone(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}contacts",
            json={"id": 1000},
            status=201,
        )
        result = runner.invoke(
            cli,
            [
                "contacts", "create",
                "--first-name", "Jane",
                "--last-name", "Doe",
                "--email", "jane@example.com",
                "--phone", "555-1234",
                "--json",
            ],
        )
        assert result.exit_code == 0
        # Verify the request body
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["email_addresses"] == [{"address": "jane@example.com", "kind": "Work"}]
        assert request_body["phone_numbers"] == [{"address": "555-1234", "kind": "Mobile"}]


class TestContactsUpdate:
    @responses.activate
    def test_update_contact(self, runner, mock_token):
        responses.add(
            responses.PUT,
            f"{BASE_URL}contacts/123",
            json={"id": 123, "first_name": "Updated"},
            status=200,
        )
        result = runner.invoke(
            cli,
            ["contacts", "update", "123", "--first-name", "Updated", "--json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["first_name"] == "Updated"

    @responses.activate
    def test_update_with_set_fields(self, runner, mock_token):
        responses.add(
            responses.PUT,
            f"{BASE_URL}contacts/123",
            json={"id": 123, "status": "Active"},
            status=200,
        )
        result = runner.invoke(
            cli,
            ["contacts", "update", "123", "--set", "status=Active", "--json"],
        )
        assert result.exit_code == 0
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["status"] == "Active"


class TestContactsDelete:
    @responses.activate
    def test_delete_contact(self, runner, mock_token):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}contacts/123",
            status=204,
        )
        result = runner.invoke(cli, ["contacts", "delete", "123", "--confirm"])
        assert result.exit_code == 0
        assert "deleted" in result.output

    def test_delete_requires_confirm(self, runner, mock_token):
        result = runner.invoke(cli, ["contacts", "delete", "123"])
        assert result.exit_code != 0  # Missing --confirm


class TestGlobalOutputOptions:
    @responses.activate
    def test_global_json_flag(self, runner, mock_token):
        """--json as global option should work."""
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/1",
            json={"id": 1, "name": "John"},
            status=200,
        )
        result = runner.invoke(cli, ["--json", "contacts", "get", "1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["id"] == 1

    @responses.activate
    def test_global_head_flag(self, runner, mock_token):
        """--head as global option should work."""
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1}, {"id": 2}, {"id": 3}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["--head", "1", "--json", "contacts", "list"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1

    @responses.activate
    def test_global_count_flag(self, runner, mock_token):
        """--count as global option should work."""
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1}, {"id": 2}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["--count", "contacts", "list"])
        assert result.exit_code == 0
        assert result.output.strip() == "2"
