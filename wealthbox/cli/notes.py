"""Note commands for the WealthBox CLI."""

from __future__ import annotations

from typing import Any

import click

from .common import handle_output, output_options, pass_client


@click.group()
def notes() -> None:
    """Manage notes (status updates)."""
    pass


@notes.command("list")
@click.option("--contact", "resource_id", type=int, required=True, help="Contact ID (required)")
@click.option("--limit", type=int, default=None, help="Max records per page")
@output_options
@pass_client(write=False)
def list_notes(client, resource_id: int, limit: int | None, **kwargs) -> None:
    """List notes for a contact."""
    ctx = click.get_current_context()
    data = client.get_notes(resource_id=resource_id)
    handle_output(ctx, data, **kwargs)


@notes.command("get")
@click.argument("note_id", type=int)
@output_options
@pass_client(write=False)
def get_note(client, note_id: int, **kwargs) -> None:
    """Get a single note by ID."""
    ctx = click.get_current_context()
    data = client.get_note(note_id)
    handle_output(ctx, data, **kwargs)


@notes.command("create")
@click.option("--content", required=True, help="Note content (use - for stdin)")
@click.option("--link-contact", type=int, required=True, help="Contact ID to link to")
@click.option("--visible-to", type=str, default=None, help="Visibility: Everyone, Owner, Team")
@click.option("--tag", multiple=True, help="Tag name (repeatable)")
@output_options
@pass_client(write=True)
def create_note(
    client,
    content: str,
    link_contact: int,
    visible_to: str | None,
    tag: tuple,
    **kwargs,
) -> None:
    """Create a new note."""
    ctx = click.get_current_context()

    # Read from stdin if content is "-"
    if content == "-":
        content = click.get_text_stream("stdin").read().strip()

    data: dict[str, Any] = {
        "content": content,
        "linked_to": [{"id": link_contact, "type": "Contact"}],
    }
    if visible_to:
        data["visible_to"] = visible_to
    if tag:
        data["tags"] = [{"name": t} for t in tag]

    result = client.create_note(data)
    handle_output(ctx, result, **kwargs)


@notes.command("update")
@click.argument("note_id", type=int)
@click.option("--content", type=str, default=None, help="Note content")
@click.option("--set", "set_fields", multiple=True, help="Set field (FIELD=VALUE)")
@output_options
@pass_client(write=True)
def update_note(
    client,
    note_id: int,
    content: str | None,
    set_fields: tuple,
    **kwargs,
) -> None:
    """Update a note by ID."""
    ctx = click.get_current_context()
    data: dict[str, Any] = {}
    if content:
        data["content"] = content
    for fv in set_fields:
        key, _, value = fv.partition("=")
        data[key] = value

    result = client.update_note(note_id, data)
    handle_output(ctx, result, **kwargs)
