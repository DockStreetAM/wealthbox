"""Tests for workflow CLI commands."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestWorkflowsList:
    @responses.activate
    def test_list_workflows(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows",
            json={
                "workflows": [{"id": 1, "name": "Onboarding"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["workflows", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1


class TestWorkflowsTemplates:
    @responses.activate
    def test_list_templates(self, runner, mock_token):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflow_templates",
            json={
                "workflow_templates": [
                    {"id": 1, "name": "New Client Onboarding"},
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["workflows", "templates", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed[0]["name"] == "New Client Onboarding"


class TestWorkflowsCreate:
    @responses.activate
    def test_create_workflow(self, runner, mock_token):
        responses.add(
            responses.POST,
            f"{BASE_URL}workflows",
            json={"id": 50, "name": "Onboarding"},
            status=201,
        )
        result = runner.invoke(
            cli,
            [
                "workflows", "create",
                "--template", "1",
                "--link-contact", "12345",
                "--json",
            ],
        )
        assert result.exit_code == 0


class TestWorkflowsCompleteStep:
    @responses.activate
    def test_complete_step(self, runner, mock_token):
        responses.add(
            responses.PUT,
            f"{BASE_URL}workflow_steps/99",
            json={"id": 99, "completed": True},
            status=200,
        )
        result = runner.invoke(cli, ["workflows", "complete-step", "99", "--json"])
        assert result.exit_code == 0
        body = json.loads(responses.calls[0].request.body)
        assert body["completed"] is True
