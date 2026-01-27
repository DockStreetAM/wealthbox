"""Event commands for the WealthBox CLI."""

from __future__ import annotations

from typing import Any

import click

from .common import handle_output, output_options, pass_client


@click.group()
def events() -> None:
    """Manage events."""
    pass


@events.command("list")
@click.option("--contact", "resource_id", type=int, default=None, help="Filter by contact ID")
@click.option("--limit", type=int, default=None, help="Max records per page")
@output_options
@pass_client(write=False)
def list_events(client, resource_id: int | None, limit: int | None, **kwargs) -> None:
    """List events with optional filters."""
    ctx = click.get_current_context()
    data = client.get_events(resource_id=resource_id)
    handle_output(ctx, data, **kwargs)


@events.command("get")
@click.argument("event_id", type=int)
@output_options
@pass_client(write=False)
def get_event(client, event_id: int, **kwargs) -> None:
    """Get a single event by ID."""
    ctx = click.get_current_context()
    data = client.get_event(event_id)
    handle_output(ctx, data, **kwargs)


@events.command("create")
@click.option("--name", required=True, help="Event name")
@click.option("--start", "starts_at", required=True, help="Start time (ISO8601)")
@click.option("--end", "ends_at", type=str, default=None, help="End time (ISO8601)")
@click.option("--all-day", is_flag=True, help="All-day event")
@click.option("--location", type=str, default=None, help="Location")
@click.option("--link-contact", type=int, default=None, help="Link to contact ID")
@click.option("--from-json", "json_data", type=str, default=None, help="JSON data string or @file path")
@output_options
@pass_client(write=True)
def create_event(
    client,
    name: str,
    starts_at: str,
    ends_at: str | None,
    all_day: bool,
    location: str | None,
    link_contact: int | None,
    json_data: str | None,
    **kwargs,
) -> None:
    """Create a new event."""
    import json as json_mod

    ctx = click.get_current_context()

    if json_data:
        if json_data.startswith("@"):
            with open(json_data[1:]) as f:
                data = json_mod.load(f)
        else:
            data = json_mod.loads(json_data)
    else:
        data: dict[str, Any] = {
            "name": name,
            "starts_at": starts_at,
        }
        if ends_at:
            data["ends_at"] = ends_at
        if all_day:
            data["all_day"] = True
        if location:
            data["location"] = location
        if link_contact:
            data["linked_to"] = [{"id": link_contact, "type": "Contact"}]

    result = client.create_event(data)
    handle_output(ctx, result, **kwargs)


@events.command("update")
@click.argument("event_id", type=int)
@click.option("--name", type=str, default=None, help="Event name")
@click.option("--start", "starts_at", type=str, default=None, help="Start time")
@click.option("--end", "ends_at", type=str, default=None, help="End time")
@click.option("--location", type=str, default=None, help="Location")
@click.option("--set", "set_fields", multiple=True, help="Set field (FIELD=VALUE)")
@output_options
@pass_client(write=True)
def update_event(
    client,
    event_id: int,
    name: str | None,
    starts_at: str | None,
    ends_at: str | None,
    location: str | None,
    set_fields: tuple,
    **kwargs,
) -> None:
    """Update an event by ID."""
    ctx = click.get_current_context()
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    if starts_at:
        data["starts_at"] = starts_at
    if ends_at:
        data["ends_at"] = ends_at
    if location:
        data["location"] = location
    for fv in set_fields:
        key, _, value = fv.partition("=")
        data[key] = value

    result = client.update_event(event_id, data)
    handle_output(ctx, result, **kwargs)


@events.command("delete")
@click.argument("event_id", type=int)
@click.option("--confirm", is_flag=True, required=True, help="Confirm deletion")
@pass_client(write=True)
def delete_event(client, event_id: int, confirm: bool) -> None:
    """Delete an event by ID. Requires --confirm flag."""
    client.delete_event(event_id)
    click.echo(f"Event {event_id} deleted.")
