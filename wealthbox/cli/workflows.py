"""Workflow commands for the WealthBox CLI."""

from __future__ import annotations

from typing import Any

import click

from .common import handle_output, output_options, pass_client


@click.group()
def workflows() -> None:
    """Manage workflows."""
    pass


@workflows.command("list")
@click.option("--contact", "resource_id", type=int, default=None, help="Filter by contact ID")
@click.option("--status", type=click.Choice(["active", "completed", "scheduled"]), default=None, help="Filter by status")
@click.option("--limit", type=int, default=None, help="Max records per page")
@output_options
@pass_client(write=False)
def list_workflows(
    client,
    resource_id: int | None,
    status: str | None,
    limit: int | None,
    **kwargs,
) -> None:
    """List workflows with optional filters."""
    ctx = click.get_current_context()
    data = client.get_workflows(resource_id=resource_id, status=status)
    handle_output(ctx, data, **kwargs)


@workflows.command("get")
@click.argument("workflow_id", type=int)
@output_options
@pass_client(write=False)
def get_workflow(client, workflow_id: int, **kwargs) -> None:
    """Get a single workflow by ID."""
    ctx = click.get_current_context()
    data = client.get_workflow(workflow_id)
    handle_output(ctx, data, **kwargs)


@workflows.command("templates")
@output_options
@pass_client(write=False)
def list_templates(client, **kwargs) -> None:
    """List available workflow templates."""
    ctx = click.get_current_context()
    data = client.get_workflow_templates()
    handle_output(ctx, data, **kwargs)


@workflows.command("create")
@click.option("--template", "template_id", type=int, required=True, help="Template ID")
@click.option("--link-contact", type=int, required=True, help="Contact ID to link to")
@click.option("--name", type=str, default=None, help="Override workflow name")
@output_options
@pass_client(write=True)
def create_workflow(
    client,
    template_id: int,
    link_contact: int,
    name: str | None,
    **kwargs,
) -> None:
    """Create a workflow from a template."""
    ctx = click.get_current_context()
    data: dict[str, Any] = {
        "template_id": template_id,
        "linked_to": [{"id": link_contact, "type": "Contact"}],
    }
    if name:
        data["name"] = name

    result = client.create_workflow(data)
    handle_output(ctx, result, **kwargs)


@workflows.command("delete")
@click.argument("workflow_id", type=int)
@click.option("--confirm", is_flag=True, required=True, help="Confirm deletion")
@pass_client(write=True)
def delete_workflow(client, workflow_id: int, confirm: bool) -> None:
    """Delete a workflow by ID. Requires --confirm flag."""
    client.delete_workflow(workflow_id)
    click.echo(f"Workflow {workflow_id} deleted.")


@workflows.command("complete-step")
@click.argument("step_id", type=int)
@output_options
@pass_client(write=True)
def complete_step(client, step_id: int, **kwargs) -> None:
    """Mark a workflow step as completed."""
    ctx = click.get_current_context()
    result = client.update_workflow_step(step_id, {"completed": True})
    handle_output(ctx, result, **kwargs)


@workflows.command("revert-step")
@click.argument("step_id", type=int)
@output_options
@pass_client(write=True)
def revert_step(client, step_id: int, **kwargs) -> None:
    """Revert a workflow step to incomplete."""
    ctx = click.get_current_context()
    result = client.update_workflow_step(step_id, {"completed": False})
    handle_output(ctx, result, **kwargs)
