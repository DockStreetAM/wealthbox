"""Shared fixtures for CLI tests."""

import os

import pytest
import responses
from click.testing import CliRunner

from wealthbox import WealthBox
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_token(monkeypatch):
    """Set a mock API token in environment."""
    monkeypatch.setenv("WEALTHBOX_ACCESS_TOKEN", "test_token_123")


@pytest.fixture
def cli_invoke(runner, mock_token):
    """Helper to invoke CLI commands with token already set."""
    def invoke(*args, **kwargs):
        return runner.invoke(cli, args, catch_exceptions=False, **kwargs)
    return invoke
