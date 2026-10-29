"""Structured error handling for the WealthBox CLI."""

from __future__ import annotations

import json
import re
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


def api_status(exc: Exception) -> int | None:
    """Best-effort HTTP status for a WealthBoxAPIError.

    Prefers a ``status_code`` attribute; otherwise parses the status out of
    the library's message ("... failed (404): ..." / "unexpected status 404").
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"failed \((\d{3})\)|unexpected status (\d{3})", str(exc))
    if match:
        return int(match.group(1) or match.group(2))
    return None


def handle_api_error(exc: Exception, use_json: bool = False) -> None:
    """Handle WealthBox API exceptions with appropriate exit codes."""
    import requests

    import wealthbox
    from wealthbox import (
        WealthBoxAPIError,
        WealthBoxRateLimitError,
        WealthBoxResponseError,
    )

    connection_error = getattr(wealthbox, "WealthBoxConnectionError", None)

    if isinstance(exc, click.UsageError):
        # e.g. a malformed --set raised from inside a command body. Click's
        # own usage exit (2) would collide with AUTH_ERROR, so map it here.
        die("VALIDATION_ERROR", exc.format_message(), ExitCode.VALIDATION_ERROR, use_json)
    elif isinstance(exc, (click.exceptions.Abort, click.exceptions.Exit)):
        raise exc
    elif isinstance(exc, WealthBoxRateLimitError):
        die("RATE_LIMIT", str(exc), ExitCode.RATE_LIMIT, use_json)
    elif (connection_error is not None and isinstance(exc, connection_error)) or isinstance(
        exc, requests.RequestException
    ):
        die("NETWORK_ERROR", str(exc), ExitCode.NETWORK_ERROR, use_json)
    elif isinstance(exc, WealthBoxAPIError):
        status = api_status(exc)
        if status == 404:
            die("NOT_FOUND", str(exc), ExitCode.NOT_FOUND, use_json)
        elif status in (400, 422):
            die("VALIDATION_ERROR", str(exc), ExitCode.VALIDATION_ERROR, use_json)
        elif status in (401, 403):
            die("AUTH_ERROR", str(exc), ExitCode.AUTH_ERROR, use_json)
        die("API_ERROR", str(exc), ExitCode.GENERAL_ERROR, use_json)
    elif isinstance(exc, WealthBoxResponseError):
        die("RESPONSE_ERROR", str(exc), ExitCode.GENERAL_ERROR, use_json)
    else:
        die("UNKNOWN_ERROR", str(exc), ExitCode.GENERAL_ERROR, use_json)
