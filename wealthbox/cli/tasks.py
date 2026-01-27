"""Task commands for the WealthBox CLI."""

from __future__ import annotations

from typing import Any

import click

from .common import handle_output, output_options, pass_client


@click.group()
def tasks() -> None:
    """Manage tasks."""
    pass


@tasks.command("list")
@click.option("--assigned-to", type=int, default=None, help="Filter by assignee user ID")
@click.option("--completed/--incomplete", default=None, help="Filter by completion status")
@click.option("--contact", "resource_id", type=int, default=None, help="Filter by linked contact ID")
@click.option("--limit", type=int, default=None, help="Max records per page")
@output_options
@pass_client(write=False)
def list_tasks(
    client,
    assigned_to: int | None,
    completed: bool | None,
    resource_id: int | None,
    limit: int | None,
    **kwargs,
) -> None:
    """List tasks with optional filters."""
    ctx = click.get_current_context()
    other_filters: dict[str, Any] = {}
    if limit:
        other_filters["per_page"] = str(limit)

    completed_val: bool | str | None = None
    if completed is True:
        completed_val = True
    elif completed is False:
        completed_val = False

    data = client.get_tasks(
        resource_id=resource_id,
        assigned_to=assigned_to,
        completed=completed_val,
        other_filters=other_filters,
    )
    handle_output(ctx, data, **kwargs)


@tasks.command("get")
@click.argument("task_id", type=int)
@output_options
@pass_client(write=False)
def get_task(client, task_id: int, **kwargs) -> None:
    """Get a single task by ID."""
    ctx = click.get_current_context()
    data = client.get_task(task_id)
    handle_output(ctx, data, **kwargs)


@tasks.command("create")
@click.option("--name", required=True, help="Task name")
@click.option("--due-date", type=str, default=None, help="Due date (YYYY-MM-DD)")
@click.option("--assigned-to", type=int, default=None, help="Assign to user ID")
@click.option("--assigned-to-team", type=int, default=None, help="Assign to team ID")
@click.option("--link-contact", type=int, default=None, help="Link to contact ID")
@click.option("--description", type=str, default=None, help="Task description")
@output_options
@pass_client(write=True)
def create_task(
    client,
    name: str,
    due_date: str | None,
    assigned_to: int | None,
    assigned_to_team: int | None,
    link_contact: int | None,
    description: str | None,
    **kwargs,
) -> None:
    """Create a new task."""
    ctx = click.get_current_context()
    data: dict[str, Any] = {"name": name}
    if due_date:
        data["due_date"] = f"{due_date}T00:00:00Z"
    if assigned_to:
        data["assigned_to"] = assigned_to
    if assigned_to_team:
        data["assigned_to_team"] = assigned_to_team
    if link_contact:
        data["linked_to"] = [{"id": link_contact, "type": "Contact"}]
    if description:
        data["description"] = description

    result = client.api_post("tasks", data)
    handle_output(ctx, result, **kwargs)


@tasks.command("update")
@click.argument("task_id", type=int)
@click.option("--name", type=str, default=None, help="Task name")
@click.option("--due-date", type=str, default=None, help="Due date (YYYY-MM-DD)")
@click.option("--completed", type=bool, default=None, help="Mark as completed")
@click.option("--description", type=str, default=None, help="Task description")
@click.option("--set", "set_fields", multiple=True, help="Set field (FIELD=VALUE)")
@output_options
@pass_client(write=True)
def update_task(
    client,
    task_id: int,
    name: str | None,
    due_date: str | None,
    completed: bool | None,
    description: str | None,
    set_fields: tuple,
    **kwargs,
) -> None:
    """Update a task by ID."""
    ctx = click.get_current_context()
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    if due_date:
        data["due_date"] = f"{due_date}T00:00:00Z"
    if completed is not None:
        data["completed"] = completed
    if description:
        data["description"] = description
    for fv in set_fields:
        key, _, value = fv.partition("=")
        data[key] = value

    result = client.update_task(task_id, data)
    handle_output(ctx, result, **kwargs)


@tasks.command("delete")
@click.argument("task_id", type=int)
@click.option("--confirm", is_flag=True, required=True, help="Confirm deletion")
@pass_client(write=True)
def delete_task(client, task_id: int, confirm: bool) -> None:
    """Delete a task by ID. Requires --confirm flag."""
    client.delete_task(task_id)
    click.echo(f"Task {task_id} deleted.")


@tasks.command("complete")
@click.argument("task_id", type=int)
@output_options
@pass_client(write=True)
def complete_task(client, task_id: int, **kwargs) -> None:
    """Mark a task as completed."""
    ctx = click.get_current_context()
    result = client.update_task(task_id, {"completed": True})
    handle_output(ctx, result, **kwargs)
