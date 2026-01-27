"""Tests for --readonly flag behavior."""

import json

import pytest
import responses

from click.testing import CliRunner
from wealthbox.cli.main import cli
from wealthbox.cli.constants import ExitCode


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    return CliRunner()


class TestReadonlyFlag:
    @responses.activate
    def test_readonly_allows_read(self, runner, mock_token):
        """--readonly should allow GET operations."""
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1, "name": "John"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["--readonly", "contacts", "list", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1

    def test_readonly_blocks_create(self, runner, mock_token):
        """--readonly should block create operations."""
        result = runner.invoke(
            cli,
            ["--readonly", "contacts", "create", "--first-name", "Test", "--last-name", "User"],
        )
        assert result.exit_code == ExitCode.READONLY_BLOCKED

    def test_readonly_blocks_update(self, runner, mock_token):
        """--readonly should block update operations."""
        result = runner.invoke(
            cli,
            ["--readonly", "contacts", "update", "123", "--first-name", "New"],
        )
        assert result.exit_code == ExitCode.READONLY_BLOCKED

    def test_readonly_blocks_delete(self, runner, mock_token):
        """--readonly should block delete operations."""
        result = runner.invoke(
            cli,
            ["--readonly", "contacts", "delete", "123", "--confirm"],
        )
        assert result.exit_code == ExitCode.READONLY_BLOCKED

    def test_readonly_blocks_task_create(self, runner, mock_token):
        """--readonly should block task creation."""
        result = runner.invoke(
            cli,
            ["--readonly", "tasks", "create", "--name", "Test task"],
        )
        assert result.exit_code == ExitCode.READONLY_BLOCKED

    def test_readonly_blocks_note_create(self, runner, mock_token):
        """--readonly should block note creation."""
        result = runner.invoke(
            cli,
            ["--readonly", "notes", "create", "--content", "Test", "--link-contact", "123"],
        )
        assert result.exit_code == ExitCode.READONLY_BLOCKED

    @responses.activate
    def test_readonly_allows_task_list(self, runner, mock_token):
        """--readonly should allow listing tasks."""
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={
                "tasks": [{"id": 1, "name": "Task 1"}],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        result = runner.invoke(cli, ["--readonly", "tasks", "list", "--json"])
        assert result.exit_code == 0

    def test_readonly_error_is_json_with_json_flag(self, runner, mock_token):
        """--readonly error should be JSON when --json flag is set."""
        result = runner.invoke(
            cli,
            ["--readonly", "--json", "contacts", "create", "--first-name", "Test", "--last-name", "User"],
        )
        assert result.exit_code == ExitCode.READONLY_BLOCKED
        # Error goes to stderr
        error = json.loads(result.output.strip() or result.output)

    @responses.activate
    def test_without_readonly_allows_write(self, runner, mock_token):
        """Without --readonly, write operations should proceed."""
        responses.add(
            responses.POST,
            f"{BASE_URL}contacts",
            json={"id": 999, "first_name": "Test", "last_name": "User"},
            status=201,
        )
        result = runner.invoke(
            cli,
            ["contacts", "create", "--first-name", "Test", "--last-name", "User", "--json"],
        )
        assert result.exit_code == 0


class TestDryRun:
    def test_dry_run_blocks_write(self, runner, mock_token):
        """--dry-run should skip write operations gracefully."""
        result = runner.invoke(
            cli,
            ["--dry-run", "contacts", "create", "--first-name", "Test", "--last-name", "User"],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
