"""Authentication commands for the WealthBox CLI."""

from __future__ import annotations

import click

from .common import handle_output, output_options, pass_client
from .config import load_token, save_token
from .constants import ExitCode
from .errors import die


@click.group()
def auth() -> None:
    """Manage authentication."""
    pass


@auth.command("set-token")
@click.argument("token")
def set_token(token: str) -> None:
    """Save an API token to ~/.config/wealthbox/credentials.json."""
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
    """Test API authentication."""
    try:
        data = client.api_request("me")
        user = data.get("current_user", {})
        name = user.get("name", "Unknown")
        click.echo(f"Authenticated as: {name}")
    except Exception:
        die("AUTH_FAILED", "Authentication failed. Check your token.", ExitCode.AUTH_ERROR)
