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


@contacts.command("export-all")
@click.option("--output-dir", "-o", type=str, default="./exports", help="Output directory for markdown files")
@click.option("--contact-type", type=str, default=None, help="Filter by contact_type: Client, Prospect, etc.")
@click.option("--dry-run", is_flag=True, help="Show what would be exported without actually exporting")
@click.option("--incremental/--full", default=True, help="Only update changed files (default) or force full rebuild")
@click.option("--comment-lookback-days", type=int, default=30, help="Days to look back for new comments on existing items")
@pass_client(write=False)
def export_all_contacts(
    client,
    output_dir: str,
    contact_type: str | None,
    dry_run: bool,
    incremental: bool,
    comment_lookback_days: int,
) -> None:
    """Export all contacts to markdown files in three phases.

    Phase 1: Export all Households (includes their members)
    Phase 2: Export Person contacts not already in a household
    Phase 3: Export Trust and Organization contacts

    Uses caching to minimize API calls across all exports.
    Incremental mode (default) only re-exports contacts with changes
    since the last export.

    \b
    Examples:
      wb contacts export-all                           # Incremental update
      wb contacts export-all -o ~/client-exports/      # Custom directory
      wb contacts export-all --contact-type Client     # Only clients
      wb contacts export-all --full                    # Force full rebuild
      wb contacts export-all --dry-run                 # Preview what would export
    """
    import os
    import re as re_mod
    from datetime import datetime, timezone

    from .export import (
        ExportCache,
        ExportMetadata,
        _slugify,
        export_contact_to_markdown,
        find_dirty_contacts,
    )

    # Create output directory if needed
    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)

    # Build filter params
    params: dict[str, Any] = {}
    if contact_type:
        params["contact_type"] = contact_type

    # Initialize cache for efficiency
    cache = ExportCache()

    # Load export metadata for incremental mode
    meta = ExportMetadata.load(output_dir)
    dirty_ids: set[int] | None = None

    if incremental and meta.last_export is not None:
        click.echo(f"Last export: {meta.last_export.isoformat()}")
        click.echo("Detecting changes...")
        dirty_ids = find_dirty_contacts(
            client, meta.last_export, cache,
            comment_lookback_days=comment_lookback_days,
        )
        if dirty_ids is not None:
            click.echo(f"Found {len(dirty_ids)} dirty contact(s)")
        else:
            click.echo("First export — exporting all contacts")
    elif not incremental:
        click.echo("Full export mode — exporting all contacts")
        dirty_ids = None
    else:
        click.echo("No previous export found — exporting all contacts")

    # Track which contact IDs we've already exported (as household members)
    exported_ids: set[int] = set()
    stats = {
        "households": 0, "persons": 0, "trusts": 0, "organizations": 0,
        "skipped": 0, "skipped_clean": 0, "errors": 0, "updated": 0,
    }

    def _is_dirty(contact_id: int, members: list[dict[str, Any]] | None = None) -> bool:
        """Check if a contact needs re-export."""
        if dirty_ids is None:
            return True  # Full export or first run
        if contact_id in dirty_ids:
            return True
        # Check if any household member is dirty
        if members:
            for member in members:
                mid = member.get("id") or member.get("contact", {}).get("id")
                if mid and mid in dirty_ids:
                    return True
        return False

    def do_export(contact: dict[str, Any], phase: str) -> None:
        """Export a single contact and track its members."""
        contact_id = contact["id"]
        name = contact.get("name", f"contact-{contact_id}")
        members = contact.get("members", [])

        if contact_id in exported_ids:
            stats["skipped"] += 1
            return

        # Check if this contact needs re-export (incremental mode)
        if not _is_dirty(contact_id, members):
            stats["skipped_clean"] += 1
            exported_ids.add(contact_id)
            # Still track household members so we don't re-export them
            for member in members:
                member_id = member.get("id") or member.get("contact", {}).get("id")
                if member_id:
                    exported_ids.add(member_id)
            return

        if dry_run:
            click.echo(f"  [{phase}] Would export: {name} (ID: {contact_id})")
            exported_ids.add(contact_id)
            # Track household members
            for member in members:
                member_id = member.get("id") or member.get("contact", {}).get("id")
                if member_id:
                    exported_ids.add(member_id)
            return

        try:
            markdown = export_contact_to_markdown(client, contact_id, cache=cache)

            # Generate filename
            match = re_mod.search(r'^title:\s*"(.+?)"', markdown, re_mod.MULTILINE)
            title = match.group(1) if match else name
            filename = f"{_slugify(title)}.md"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "w") as f:
                f.write(markdown)

            click.echo(f"  [{phase}] {name} -> {filename}")
            exported_ids.add(contact_id)
            stats["updated"] += 1

            # Track in metadata
            meta.contact_files[contact_id] = filename

            # Track household members so we don't re-export them
            for member in members:
                member_id = member.get("id") or member.get("contact", {}).get("id")
                if member_id:
                    exported_ids.add(member_id)

        except Exception as e:
            click.echo(f"  [{phase}] ERROR exporting {name}: {e}", err=True)
            stats["errors"] += 1

    # Phase 1: Households
    click.echo("\n=== Phase 1: Households ===")
    household_params = {**params, "type": "Household"}
    households = client.get_contacts(filters=household_params)
    click.echo(f"Found {len(households)} households")

    for i, hh in enumerate(households, 1):
        if not dry_run:
            click.echo(f"[{i}/{len(households)}]", nl=False)
        do_export(hh, "HH")
        stats["households"] += 1

    # Phase 2: Persons not in households
    click.echo("\n=== Phase 2: Individual Persons ===")
    person_params = {**params, "type": "Person"}
    persons = client.get_contacts(filters=person_params)
    not_in_hh = [p for p in persons if p["id"] not in exported_ids]
    click.echo(f"Found {len(persons)} persons, {len(not_in_hh)} not in households")

    for i, person in enumerate(not_in_hh, 1):
        if not dry_run:
            click.echo(f"[{i}/{len(not_in_hh)}]", nl=False)
        do_export(person, "Person")
        stats["persons"] += 1

    # Phase 3: Trusts and Organizations
    click.echo("\n=== Phase 3: Trusts & Organizations ===")

    trust_params = {**params, "type": "Trust"}
    trusts = client.get_contacts(filters=trust_params)
    click.echo(f"Found {len(trusts)} trusts")

    for i, trust in enumerate(trusts, 1):
        if not dry_run:
            click.echo(f"[{i}/{len(trusts)}]", nl=False)
        do_export(trust, "Trust")
        stats["trusts"] += 1

    org_params = {**params, "type": "Organization"}
    orgs = client.get_contacts(filters=org_params)
    click.echo(f"Found {len(orgs)} organizations")

    for i, org in enumerate(orgs, 1):
        if not dry_run:
            click.echo(f"[{i}/{len(orgs)}]", nl=False)
        do_export(org, "Org")
        stats["organizations"] += 1

    # Save metadata
    if not dry_run:
        meta.last_export = datetime.now(timezone.utc)
        meta.save(output_dir)

    # Summary
    click.echo("\n=== Summary ===")
    click.echo(f"Households:    {stats['households']}")
    click.echo(f"Persons:       {stats['persons']}")
    click.echo(f"Trusts:        {stats['trusts']}")
    click.echo(f"Organizations: {stats['organizations']}")
    click.echo(f"Skipped (dup): {stats['skipped']}")
    if stats["skipped_clean"]:
        click.echo(f"Skipped (clean): {stats['skipped_clean']}")
    if stats["errors"]:
        click.echo(f"Errors:        {stats['errors']}")
    click.echo(f"Files updated: {stats['updated']}")
    click.echo(f"Total contacts: {len(exported_ids)}")
