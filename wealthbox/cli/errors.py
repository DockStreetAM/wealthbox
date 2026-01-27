"""Structured error handling for the WealthBox CLI."""

from __future__ import annotations

import json
import sys

import click

from .constants import ExitCode


def error_json(code: str, message: str, exit_code: ExitCode) -> dict:
    """Build a structured error dict."""
    return {
        "error": True,
        "code": code,
        "message": message,
        "exit_code": int(exit_code),
    }


def die(
    code: str,
    message: str,
    exit_code: ExitCode = ExitCode.GENERAL_ERROR,
    use_json: bool = False,
) -> None:
    """Print error and exit."""
    if use_json:
        click.echo(json.dumps(error_json(code, message, exit_code)), err=True)
    else:
        click.echo(f"Error: {message}", err=True)
    sys.exit(int(exit_code))


def handle_api_error(exc: Exception, use_json: bool = False) -> None:
    """Handle WealthBox API exceptions with appropriate exit codes."""
    from wealthbox import (
        WealthBoxAPIError,
        WealthBoxRateLimitError,
        WealthBoxResponseError,
    )

    if isinstance(exc, WealthBoxRateLimitError):
        die("RATE_LIMIT", str(exc), ExitCode.RATE_LIMIT, use_json)
    elif isinstance(exc, WealthBoxAPIError):
        die("API_ERROR", str(exc), ExitCode.GENERAL_ERROR, use_json)
    elif isinstance(exc, WealthBoxResponseError):
        die("RESPONSE_ERROR", str(exc), ExitCode.GENERAL_ERROR, use_json)
    else:
        die("UNKNOWN_ERROR", str(exc), ExitCode.GENERAL_ERROR, use_json)
