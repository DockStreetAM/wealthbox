"""Contact commands for the WealthBox CLI."""

from __future__ import annotations

from typing import Any

import click

from .common import handle_output, output_options, pass_client


@click.group()
def contacts() -> None:
    """Manage contacts (people, households, organizations)."""
    pass


@contacts.command("list")
@click.option("--type", "contact_type_filter", type=str, default=None, help="Filter by type: Person, Household, Organization")
@click.option("--contact-type", type=str, default=None, help="Filter by contact_type: Client, Prospect, etc.")
@click.option("--tag", type=str, default=None, help="Filter by tag name")
@click.option("--search", type=str, default=None, help="Full-text search query")
@click.option("--updated-since", type=str, default=None, help="Filter by updated_since (ISO8601)")
@click.option("--limit", type=int, default=None, help="Max records per page")
@output_options
@pass_client(write=False)
def list_contacts(
    client,
    contact_type_filter: str | None,
    contact_type: str | None,
    tag: str | None,
    search: str | None,
    updated_since: str | None,
    limit: int | None,
    **kwargs,
) -> None:
    """List contacts with optional filters."""
    ctx = click.get_current_context()
    params: dict[str, Any] = {}
    if contact_type_filter:
        params["type"] = contact_type_filter
    if contact_type:
        params["contact_type"] = contact_type
    if tag:
        params["tag"] = tag
    if search:
        params["name"] = search
    if updated_since:
        params["updated_since"] = updated_since
    if limit:
        params["per_page"] = str(limit)

    data = client.get_contacts(filters=params)
    handle_output(ctx, data, **kwargs)


@contacts.command("get")
@click.argument("contact_id", type=int)
@output_options
@pass_client(write=False)
def get_contact(client, contact_id: int, **kwargs) -> None:
    """Get a single contact by ID."""
    ctx = click.get_current_context()
    data = client.get_contact(contact_id)
    handle_output(ctx, data, **kwargs)


@contacts.command("search")
@click.argument("query")
@output_options
@pass_client(write=False)
def search_contacts(client, query: str, **kwargs) -> None:
    """Search contacts by name."""
    ctx = click.get_current_context()
    data = client.get_contact_by_name(query)
    handle_output(ctx, data, **kwargs)


@contacts.command("create")
@click.option("--first-name", type=str, default=None, help="First name")
@click.option("--last-name", type=str, default=None, help="Last name")
@click.option("--type", "contact_type_value", type=str, default="Person", help="Person, Household, or Organization")
@click.option("--contact-type", type=str, default=None, help="Client, Prospect, Beneficiary, etc.")
@click.option("--email", type=str, default=None, help="Email address")
@click.option("--phone", type=str, default=None, help="Phone number")
@click.option("--birth-date", type=str, default=None, help="Birth date (YYYY-MM-DD)")
@click.option("--tag", multiple=True, help="Tag name (repeatable)")
@click.option("--from-json", "json_data", type=str, default=None, help="JSON data string or @file path")
@output_options
@pass_client(write=True)
def create_contact(
    client,
    first_name: str | None,
    last_name: str | None,
    contact_type_value: str,
    contact_type: str | None,
    email: str | None,
    phone: str | None,
    birth_date: str | None,
    tag: tuple,
    json_data: str | None,
    **kwargs,
) -> None:
    """Create a new contact."""
    import json as json_mod

    ctx = click.get_current_context()

    if json_data:
        if json_data.startswith("@"):
            with open(json_data[1:]) as f:
                data = json_mod.load(f)
        else:
            data = json_mod.loads(json_data)
    else:
        data: dict[str, Any] = {"type": contact_type_value}
        if first_name:
            data["first_name"] = first_name
        if last_name:
            data["last_name"] = last_name
        if contact_type:
            data["contact_type"] = contact_type
        if email:
            data["email_addresses"] = [{"address": email, "kind": "Work"}]
        if phone:
            data["phone_numbers"] = [{"address": phone, "kind": "Mobile"}]
        if birth_date:
            data["birth_date"] = birth_date
        if tag:
            data["tags"] = [{"name": t} for t in tag]

    result = client.create_contact(data)
    handle_output(ctx, result, **kwargs)


@contacts.command("update")
@click.argument("contact_id", type=int)
@click.option("--first-name", type=str, default=None, help="First name")
@click.option("--last-name", type=str, default=None, help="Last name")
@click.option("--contact-type", type=str, default=None, help="Contact type")
@click.option("--email", type=str, default=None, help="Email address")
@click.option("--phone", type=str, default=None, help="Phone number")
@click.option("--set", "set_fields", multiple=True, help="Set field value (FIELD=VALUE, repeatable)")
@click.option("--from-json", "json_data", type=str, default=None, help="JSON data string or @file path")
@output_options
@pass_client(write=True)
def update_contact(
    client,
    contact_id: int,
    first_name: str | None,
    last_name: str | None,
    contact_type: str | None,
    email: str | None,
    phone: str | None,
    set_fields: tuple,
    json_data: str | None,
    **kwargs,
) -> None:
    """Update an existing contact."""
    import json as json_mod

    ctx = click.get_current_context()

    if json_data:
        if json_data.startswith("@"):
            with open(json_data[1:]) as f:
                data = json_mod.load(f)
        else:
            data = json_mod.loads(json_data)
    else:
        data: dict[str, Any] = {}
        if first_name:
            data["first_name"] = first_name
        if last_name:
            data["last_name"] = last_name
        if contact_type:
            data["contact_type"] = contact_type
        if email:
            data["email_addresses"] = [{"address": email, "kind": "Work"}]
        if phone:
            data["phone_numbers"] = [{"address": phone, "kind": "Mobile"}]
        for field_val in set_fields:
            key, _, value = field_val.partition("=")
            data[key] = value

    result = client.update_contact(contact_id, data)
    handle_output(ctx, result, **kwargs)


@contacts.command("delete")
@click.argument("contact_id", type=int)
@click.option("--confirm", is_flag=True, required=True, help="Confirm deletion")
@pass_client(write=True)
def delete_contact(client, contact_id: int, confirm: bool) -> None:
    """Delete a contact by ID. Requires --confirm flag."""
    client.delete_contact(contact_id)
    click.echo(f"Contact {contact_id} deleted.")


@contacts.command("export")
@click.argument("contact_id", type=int)
@click.option("--output", "-o", "output_file", type=str, default=None, help="Write to specific file path")
@click.option("--stdout", is_flag=True, help="Print to terminal instead of writing file")
@pass_client(write=False)
def export_contact(client, contact_id: int, output_file: str | None, stdout: bool) -> None:
    """Export a contact to markdown with full activity timeline.

    Exports the contact (and their household) to a QMD-compatible markdown
    file with frontmatter metadata, contact info, and a unified activity
    timeline including notes, tasks, events, workflows, and opportunities.

    \b
    Examples:
      wb contacts export 12345 --stdout          # Print to terminal
      wb contacts export 12345                    # Auto-named file
      wb contacts export 12345 -o client.md       # Specific file
    """
    import re as re_mod

    from .export import _slugify, export_contact_to_markdown

    markdown = export_contact_to_markdown(client, contact_id)

    if stdout:
        click.echo(markdown)
    else:
        if output_file is None:
            # Auto-generate filename from frontmatter title
            match = re_mod.search(r'^title:\s*"(.+?)"', markdown, re_mod.MULTILINE)
            name = match.group(1) if match else f"contact-{contact_id}"
            output_file = f"{_slugify(name)}-{contact_id}.md"

        with open(output_file, "w") as f:
            f.write(markdown)
        click.echo(f"Exported to {output_file}")
