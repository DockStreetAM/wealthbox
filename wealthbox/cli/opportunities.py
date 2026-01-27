"""Opportunity commands for the WealthBox CLI."""

from __future__ import annotations

from typing import Any

import click

from .common import handle_output, output_options, pass_client


@click.group()
def opportunities() -> None:
    """Manage opportunities (sales pipeline)."""
    pass


@opportunities.command("list")
@click.option("--contact", "resource_id", type=int, default=None, help="Filter by contact ID")
@click.option("--order", type=click.Choice(["asc", "desc"]), default="asc", help="Sort order")
@click.option("--include-closed/--no-include-closed", default=True, help="Include closed opportunities")
@click.option("--limit", type=int, default=None, help="Max records per page")
@output_options
@pass_client(write=False)
def list_opportunities(
    client,
    resource_id: int | None,
    order: str,
    include_closed: bool,
    limit: int | None,
    **kwargs,
) -> None:
    """List opportunities with optional filters."""
    ctx = click.get_current_context()
    data = client.get_opportunities(
        resource_id=resource_id,
        order=order,
        include_closed=include_closed,
    )
    handle_output(ctx, data, **kwargs)


@opportunities.command("get")
@click.argument("opportunity_id", type=int)
@output_options
@pass_client(write=False)
def get_opportunity(client, opportunity_id: int, **kwargs) -> None:
    """Get a single opportunity by ID."""
    ctx = click.get_current_context()
    data = client.get_opportunity(opportunity_id)
    handle_output(ctx, data, **kwargs)


@opportunities.command("create")
@click.option("--name", required=True, help="Opportunity name")
@click.option("--value", type=float, default=None, help="Dollar value")
@click.option("--stage", type=str, default=None, help="Pipeline stage")
@click.option("--link-contact", type=int, default=None, help="Link to contact ID")
@click.option("--close-date", type=str, default=None, help="Expected close date (YYYY-MM-DD)")
@click.option("--from-json", "json_data", type=str, default=None, help="JSON data or @file")
@output_options
@pass_client(write=True)
def create_opportunity(
    client,
    name: str,
    value: float | None,
    stage: str | None,
    link_contact: int | None,
    close_date: str | None,
    json_data: str | None,
    **kwargs,
) -> None:
    """Create a new opportunity."""
    import json as json_mod

    ctx = click.get_current_context()

    if json_data:
        if json_data.startswith("@"):
            with open(json_data[1:]) as f:
                data = json_mod.load(f)
        else:
            data = json_mod.loads(json_data)
    else:
        data: dict[str, Any] = {"name": name}
        if value is not None:
            data["value"] = value
        if stage:
            data["stage"] = stage
        if link_contact:
            data["linked_to"] = [{"id": link_contact, "type": "Contact"}]
        if close_date:
            data["close_date"] = close_date

    result = client.create_opportunity(data)
    handle_output(ctx, result, **kwargs)


@opportunities.command("update")
@click.argument("opportunity_id", type=int)
@click.option("--name", type=str, default=None, help="Opportunity name")
@click.option("--value", type=float, default=None, help="Dollar value")
@click.option("--stage", type=str, default=None, help="Pipeline stage")
@click.option("--set", "set_fields", multiple=True, help="Set field (FIELD=VALUE)")
@output_options
@pass_client(write=True)
def update_opportunity(
    client,
    opportunity_id: int,
    name: str | None,
    value: float | None,
    stage: str | None,
    set_fields: tuple,
    **kwargs,
) -> None:
    """Update an opportunity by ID."""
    ctx = click.get_current_context()
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    if value is not None:
        data["value"] = value
    if stage:
        data["stage"] = stage
    for fv in set_fields:
        key, _, val = fv.partition("=")
        data[key] = val

    result = client.update_opportunity(opportunity_id, data)
    handle_output(ctx, result, **kwargs)


@opportunities.command("delete")
@click.argument("opportunity_id", type=int)
@click.option("--confirm", is_flag=True, required=True, help="Confirm deletion")
@pass_client(write=True)
def delete_opportunity(client, opportunity_id: int, confirm: bool) -> None:
    """Delete an opportunity by ID. Requires --confirm flag."""
    client.delete_opportunity(opportunity_id)
    click.echo(f"Opportunity {opportunity_id} deleted.")
