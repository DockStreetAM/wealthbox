"""Project commands for the WealthBox CLI."""

from __future__ import annotations

from typing import Any

import click

from .common import handle_output, output_options, pass_client


@click.group()
def projects() -> None:
    """Manage projects."""
    pass


@projects.command("list")
@click.option("--limit", type=int, default=None, help="Max records per page")
@output_options
@pass_client(write=False)
def list_projects(client, limit: int | None, **kwargs) -> None:
    """List projects."""
    ctx = click.get_current_context()
    params: dict[str, Any] = {}
    if limit:
        params["per_page"] = str(limit)
    data = client.get_projects(filters=params)
    handle_output(ctx, data, **kwargs)


@projects.command("get")
@click.argument("project_id", type=int)
@output_options
@pass_client(write=False)
def get_project(client, project_id: int, **kwargs) -> None:
    """Get a single project by ID."""
    ctx = click.get_current_context()
    data = client.get_project(project_id)
    handle_output(ctx, data, **kwargs)


@projects.command("create")
@click.option("--name", required=True, help="Project name")
@click.option("--link-contact", type=int, default=None, help="Link to contact ID")
@click.option("--description", type=str, default=None, help="Project description")
@click.option("--from-json", "json_data", type=str, default=None, help="JSON data or @file")
@output_options
@pass_client(write=True)
def create_project(
    client,
    name: str,
    link_contact: int | None,
    description: str | None,
    json_data: str | None,
    **kwargs,
) -> None:
    """Create a new project."""
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
        if link_contact:
            data["linked_to"] = [{"id": link_contact, "type": "Contact"}]
        if description:
            data["description"] = description

    result = client.create_project(data)
    handle_output(ctx, result, **kwargs)


@projects.command("update")
@click.argument("project_id", type=int)
@click.option("--name", type=str, default=None, help="Project name")
@click.option("--description", type=str, default=None, help="Project description")
@click.option("--set", "set_fields", multiple=True, help="Set field (FIELD=VALUE)")
@output_options
@pass_client(write=True)
def update_project(
    client,
    project_id: int,
    name: str | None,
    description: str | None,
    set_fields: tuple,
    **kwargs,
) -> None:
    """Update a project by ID."""
    ctx = click.get_current_context()
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    if description:
        data["description"] = description
    for fv in set_fields:
        key, _, value = fv.partition("=")
        data[key] = value

    result = client.update_project(project_id, data)
    handle_output(ctx, result, **kwargs)


@projects.command("delete")
@click.argument("project_id", type=int)
@click.option("--confirm", is_flag=True, required=True, help="Confirm deletion")
@pass_client(write=True)
def delete_project(client, project_id: int, confirm: bool) -> None:
    """Delete a project by ID. Requires --confirm flag."""
    client.delete_project(project_id)
    click.echo(f"Project {project_id} deleted.")
