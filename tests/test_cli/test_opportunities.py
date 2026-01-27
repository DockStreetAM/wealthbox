"""Tests for opportunity CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestOpportunitiesList:
    @responses.activate
    def test_list_opportunities(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities",
            json={
                "opportunities": [{"id": 1, "name": "Big deal"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["opportunities", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1


class TestOpportunitiesGet:
    @responses.activate
    def test_get_opportunity(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities/5",
            json={"id": 5, "name": "Big deal", "value": 50000},
            status=200,
        )
        result = runner.invoke(cli, ["opportunities", "get", "5", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["value"] == 50000


class TestOpportunitiesCreate:
    @responses.activate
    def test_create_opportunity(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}opportunities",
            json={"id": 10, "name": "New deal"},
            status=201,
        )
        result = runner.invoke(
            cli,
            ["opportunities", "create", "--name", "New deal", "--value", "100000", "--json"],
        )
        assert result.exit_code == 0
        body = json.loads(responses.calls[0].request.body)
        assert body["name"] == "New deal"
        assert body["value"] == 100000.0


class TestOpportunitiesDelete:
    @responses.activate
    def test_delete_opportunity(self, runner, mock_token):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}opportunities/5",
            status=204,
        )
        result = runner.invoke(cli, ["opportunities", "delete", "5", "--confirm"])
        assert result.exit_code == 0
