"""Main Click application for the WealthBox CLI."""

from __future__ import annotations

try:
    import click
except ImportError:
    import sys
    print("Error: CLI dependencies not installed.", file=sys.stderr)
    print("Install with: pip install 'wealthbox[cli]'", file=sys.stderr)
    sys.exit(1)

from wealthbox import __version__


@click.group()
@click.version_option(version=__version__, prog_name="wb")
@click.option("--readonly", is_flag=True, help="Block all write operations (for AI permission control)")
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.option("--table", "use_table", is_flag=True, help="Output as table")
@click.option("--csv", "use_csv", is_flag=True, help="Output as CSV")
@click.option("--no-headers", is_flag=True, help="Omit headers in table/CSV output")
@click.option("--fields", type=str, default=None, help="Comma-separated fields to include")
@click.option("--head", type=int, default=None, help="Show only first N records")
@click.option("--count", is_flag=True, help="Output record count only")
@click.option("--oneline", is_flag=True, help="One JSON object per line")
@click.option("--output", type=str, default=None, help="Write output to file")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--debug", is_flag=True, help="Show full request/response for debugging")
@click.option("--timeout", type=int, default=60, help="Request timeout in seconds")
@click.option("--retry", type=int, default=3, help="Number of retries on failure")
@click.option("--dry-run", is_flag=True, help="Preview write operations without executing")
@click.pass_context
def cli(
    ctx: click.Context,
    readonly: bool,
    use_json: bool,
    use_table: bool,
    use_csv: bool,
    no_headers: bool,
    fields: str | None,
    head: int | None,
    count: bool,
    oneline: bool,
    output: str | None,
    verbose: bool,
    debug: bool,
    timeout: int,
    retry: int,
    dry_run: bool,
) -> None:
    """WealthBox CRM command line interface.

    Access your WealthBox CRM data from the command line. Designed for
    both human users and AI agents.

    \b
    Quick start:
      export WEALTHBOX_ACCESS_TOKEN="your-token"
      wb contacts list --limit 5
      wb contacts get 12345

    \b
    AI agent usage:
      wb --readonly contacts list --json    # Safe read-only access
      wb contacts create --first-name John  # Write (needs explicit permission)
    """
    ctx.ensure_object(dict)
    ctx.obj["readonly"] = readonly
    ctx.obj["json"] = use_json
    ctx.obj["table"] = use_table
    ctx.obj["csv"] = use_csv
    ctx.obj["no_headers"] = no_headers
    ctx.obj["fields"] = fields
    ctx.obj["head"] = head
    ctx.obj["count"] = count
    ctx.obj["oneline"] = oneline
    ctx.obj["output"] = output
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug
    ctx.obj["timeout"] = timeout
    ctx.obj["retry"] = retry
    ctx.obj["dry_run"] = dry_run


# Import and register command groups
from .auth import auth  # noqa: E402
from .contacts import contacts  # noqa: E402
from .tasks import tasks  # noqa: E402
from .events import events  # noqa: E402
from .notes import notes  # noqa: E402
from .workflows import workflows  # noqa: E402
from .opportunities import opportunities  # noqa: E402
from .projects import projects  # noqa: E402

cli.add_command(auth)
cli.add_command(contacts)
cli.add_command(tasks)
cli.add_command(events)
cli.add_command(notes)
cli.add_command(workflows)
cli.add_command(opportunities)
cli.add_command(projects)
