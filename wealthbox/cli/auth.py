"""Authentication commands for the WealthBox CLI."""

from __future__ import annotations

from pathlib import Path

import click

from .common import handle_output, output_options, pass_client
from .config import _token_from_env_file, load_token, save_token
from .constants import ExitCode
from .errors import api_status, die
from .output import sanitize_text


@click.group()
def auth() -> None:
    """Manage authentication."""
    pass


@auth.command("set-token")
@click.argument("token", required=False)
@click.option(
    "--from-env",
    "from_env",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Copy WEALTHBOX_ACCESS_TOKEN from this .env file (e.g. a project "
    ".env that wb read automatically before 0.18.0). The token is not printed.",
)
@click.pass_context
def set_token(ctx: click.Context, token: str | None, from_env: Path | None) -> None:
    """Save an API token to ~/.config/wealthbox/credentials.json.

    \b
    Ways to provide the token:
      wb auth set-token                   # hidden prompt (needs a terminal)
      wb auth set-token --from-env .env   # copy from a .env file
      printf %s "$TOKEN" | wb auth set-token -   # read from stdin
    Passing the token as an argument still works but leaves it in shell
    history and the process list.

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
    use_json = obj.get("json", False)
    if from_env is not None:
        if token is not None:
            die("VALIDATION_ERROR", "Give either a TOKEN argument or --from-env, not both",
                ExitCode.VALIDATION_ERROR, use_json=use_json)
        if not from_env.is_file():
            die("VALIDATION_ERROR", f"--from-env: file not found: {from_env}",
                ExitCode.VALIDATION_ERROR, use_json=use_json)
        token = _token_from_env_file(from_env)
        if not token:
            die("VALIDATION_ERROR", f"--from-env: no WEALTHBOX_ACCESS_TOKEN in {from_env}",
                ExitCode.VALIDATION_ERROR, use_json=use_json)
    elif token is None:
        try:
            token = click.prompt("API token", hide_input=True)
        except click.Abort:
            # EOF on the prompt: usually no terminal (e.g. run from an editor,
            # agent, or script), so the hidden prompt can't read input
            die(
                "VALIDATION_ERROR",
                "Couldn't read the token from the prompt (no terminal?). Run "
                "`wb auth set-token` in a regular terminal, or use "
                "`wb auth set-token --from-env PATH`, or pipe the token into "
                "`wb auth set-token -`.",
                ExitCode.VALIDATION_ERROR,
                use_json=use_json,
            )
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
