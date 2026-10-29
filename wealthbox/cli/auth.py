"""Authentication commands for the WealthBox CLI."""

from __future__ import annotations

import click

from .common import handle_output, output_options, pass_client
from .config import load_token, save_token
from .constants import ExitCode
from .errors import api_status, die
from .output import sanitize_text


@click.group()
def auth() -> None:
    """Manage authentication."""
    pass


@auth.command("set-token")
@click.argument("token", required=False)
@click.pass_context
def set_token(ctx: click.Context, token: str | None) -> None:
    """Save an API token to ~/.config/wealthbox/credentials.json.

    Run with no argument to be prompted (input hidden) — recommended.
    Use "-" to read the token from stdin. Passing the token as an argument
    still works but leaves it in shell history and the process list.

    Blocked under --readonly.
    """
    obj = ctx.obj or {}
    if obj.get("readonly"):
        die(
            "READONLY_MODE",
            "auth set-token is blocked in --readonly mode",
            ExitCode.READONLY_BLOCKED,
            use_json=obj.get("json", False),
        )
    if token is None:
        token = click.prompt("API token", hide_input=True)
    elif token == "-":
        token = click.get_text_stream("stdin").read().strip()
    else:
        click.echo(
            "Warning: a token passed as an argument is saved in shell history. "
            "Prefer `wb auth set-token` with no argument.",
            err=True,
        )
    if not token:
        die("VALIDATION_ERROR", "Empty token", ExitCode.VALIDATION_ERROR, use_json=obj.get("json", False))
    path = save_token(token)
    click.echo(f"Token saved to {path}")


@auth.command("whoami")
@output_options
@pass_client(write=False)
def whoami(client, **kwargs) -> None:
    """Show current user information."""
    ctx = click.get_current_context()
    data = client.api_request("me")
    handle_output(ctx, data, **kwargs)


@auth.command("test")
@pass_client(write=False)
def test(client) -> None:
    """Test API authentication.

    Reports an authentication failure only on HTTP 401/403; network and
    server errors exit with their own codes so you don't rotate a good token.
    """
    from wealthbox import WealthBoxAPIError

    try:
        data = client.api_request("me")
    except WealthBoxAPIError as exc:
        if api_status(exc) in (401, 403):
            die("AUTH_FAILED", "Authentication failed. Check your token.", ExitCode.AUTH_ERROR)
        raise
    user = data.get("current_user", {})
    name = sanitize_text(str(user.get("name", "Unknown")))
    click.echo(f"Authenticated as: {name}")
