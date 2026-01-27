"""Shared decorators and utilities for the WealthBox CLI."""

from __future__ import annotations

import functools
import sys
from typing import Any, Callable

import click

from .config import load_token
from .constants import ExitCode
from .errors import die, handle_api_error


def get_output_opts(ctx: click.Context) -> dict[str, Any]:
    """Extract output options from Click context."""
    obj = ctx.obj or {}
    fmt = None
    if obj.get("json"):
        fmt = "json"
    elif obj.get("table"):
        fmt = "table"
    elif obj.get("csv"):
        fmt = "csv"
    return {
        "fmt": fmt,
        "fields": obj.get("fields"),
        "head": obj.get("head"),
        "count": obj.get("count"),
        "oneline": obj.get("oneline"),
        "output_file": obj.get("output"),
        "no_headers": obj.get("no_headers"),
    }


def pass_client(write: bool = False) -> Callable:
    """Decorator that injects a WealthBox client into the command.

    Args:
        write: If True, this is a write operation that will be blocked by --readonly.
    """
    def decorator(f: Callable) -> Callable:
        @click.pass_context
        @functools.wraps(f)
        def wrapper(ctx: click.Context, *args: Any, **kwargs: Any) -> Any:
            obj = ctx.obj or {}
            use_json = obj.get("json", False)

            # Check readonly mode
            if write and obj.get("readonly"):
                die(
                    "READONLY_MODE",
                    "Write operations are blocked in --readonly mode",
                    ExitCode.READONLY_BLOCKED,
                    use_json=use_json,
                )

            # Check dry-run mode for write operations
            if write and obj.get("dry_run"):
                click.echo("Dry run: would execute write operation (skipped)")
                return

            # Get or create client
            client = obj.get("client")
            if client is None:
                token = load_token()
                if not token:
                    die(
                        "AUTH_REQUIRED",
                        "No API token found. Set WEALTHBOX_ACCESS_TOKEN or run: wb auth set-token <token>",
                        ExitCode.AUTH_ERROR,
                        use_json=use_json,
                    )

                from wealthbox import WealthBox
                timeout = obj.get("timeout", 60)
                retry = obj.get("retry", 3)
                client = WealthBox(
                    token=token,
                    max_retries=retry,
                    backoff_factor=0.5,
                )
                obj["client"] = client

            try:
                return ctx.invoke(f, client=client, *args, **kwargs)
            except Exception as exc:
                handle_api_error(exc, use_json=use_json)

        return wrapper
    return decorator


def output_options(f: Callable) -> Callable:
    """Add standard output options to a command."""
    f = click.option("--json", "fmt_json", is_flag=True, help="Output as JSON")(f)
    f = click.option("--table", "fmt_table", is_flag=True, help="Output as table")(f)
    f = click.option("--csv", "fmt_csv", is_flag=True, help="Output as CSV")(f)
    f = click.option("--no-headers", is_flag=True, help="Omit headers in table/CSV")(f)
    f = click.option("--fields", type=str, default=None, help="Comma-separated fields to include")(f)
    f = click.option("--head", type=int, default=None, help="Show only first N records")(f)
    f = click.option("--count", is_flag=True, help="Output record count only")(f)
    f = click.option("--oneline", is_flag=True, help="One JSON object per line")(f)
    f = click.option("--output", "output_file", type=str, default=None, help="Write output to file")(f)
    return f


def handle_output(
    ctx: click.Context,
    data: Any,
    *,
    fmt_json: bool = False,
    fmt_table: bool = False,
    fmt_csv: bool = False,
    no_headers: bool = False,
    fields: str | None = None,
    head: int | None = None,
    count: bool = False,
    oneline: bool = False,
    output_file: str | None = None,
) -> None:
    """Process output using local options, falling back to global options."""
    from .output import output as do_output

    obj = ctx.obj or {}

    # Local options override global
    fmt = None
    if fmt_json or obj.get("json"):
        fmt = "json"
    elif fmt_table or obj.get("table"):
        fmt = "table"
    elif fmt_csv or obj.get("csv"):
        fmt = "csv"

    do_output(
        data,
        fmt=fmt,
        fields=fields or obj.get("fields"),
        head=head if head is not None else obj.get("head"),
        count=count or obj.get("count", False),
        oneline=oneline or obj.get("oneline", False),
        output_file=output_file or obj.get("output"),
        no_headers=no_headers or obj.get("no_headers", False),
    )
