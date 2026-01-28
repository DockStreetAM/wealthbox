"""Contact export to markdown for the WealthBox CLI."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any


# ---------------------------------------------------------------------------
# HTML → Markdown converter (stdlib only)
# ---------------------------------------------------------------------------

class _HTMLToMarkdownConverter(HTMLParser):
    """Convert simple HTML (as found in WealthBox notes) to markdown."""

    def __init__(self) -> None:
        super().__init__()
        self._output: list[str] = []
        self._links: list[str] = []
        self._in_link = False
        self._link_url = ""
        self._link_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag in ("b", "strong"):
            self._output.append("**")
        elif tag in ("i", "em"):
            self._output.append("*")
        elif tag == "br":
            self._output.append("\n")
        elif tag == "a":
            self._in_link = True
            self._link_url = attrs_dict.get("href", "")
            self._link_text_parts = []
        elif tag == "ul":
            self._output.append("\n")
        elif tag == "li":
            self._output.append("- ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("b", "strong"):
            self._output.append("**")
        elif tag in ("i", "em"):
            self._output.append("*")
        elif tag == "p":
            self._output.append("\n\n")
        elif tag == "a" and self._in_link:
            text = "".join(self._link_text_parts)
            num = len(self._links) + 1
            self._links.append(self._link_url)
            self._output.append(f"{text} [{num}]")
            self._in_link = False
        elif tag == "li":
            self._output.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_text_parts.append(data)
        else:
            self._output.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in ("br", "br/"):
            self._output.append("\n")

    def get_result(self) -> str:
        text = "".join(self._output)
        if self._links:
            text = text.rstrip() + "\n\n"
            for i, url in enumerate(self._links, 1):
                text += f"[{i}]: {url}\n"
        return text.strip()


def _collapse_newlines(text: str) -> str:
    """Collapse excessive blank lines while preserving paragraph breaks.

    Heuristic: if the text is mostly short lines (structured/tabular data
    like CurrentClient call logs), remove blank lines entirely and use
    single newlines.  If it contains real paragraphs, keep one blank line
    between them.
    """
    lines = [line.rstrip() for line in text.split("\n")]
    content_lines = [l for l in lines if l.strip()]
    if not content_lines:
        return text.strip()

    # Decide mode: if most content lines are short and blanks are dense,
    # treat as structured/tabular data and remove blank lines.
    median_len = sorted(len(l) for l in content_lines)[len(content_lines) // 2]
    blank_count = len(lines) - len(content_lines)
    compact = (
        median_len < 60
        and blank_count * 2 >= len(content_lines)
        and len(content_lines) >= 4
    )

    if compact:
        # Remove all blank lines — single newlines only
        return "\n".join(content_lines)

    # Normal mode: collapse runs of blank lines to at most one
    collapsed: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
        else:
            if blank_run > 0:
                collapsed.append("")
            blank_run = 0
            collapsed.append(line)
    return "\n".join(collapsed)


def _html_to_markdown(html_str: str) -> str:
    """Convert HTML content to readable markdown."""
    if not html_str:
        return ""
    if "<" not in html_str:
        return html_str
    converter = _HTMLToMarkdownConverter()
    converter.feed(html_str)
    result = converter.get_result()
    return _collapse_newlines(result)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_wb_date(date_str: str | None) -> datetime | None:
    """Parse a WealthBox date string into a datetime."""
    if not date_str:
        return None
    # WB format: "2023-06-21 03:32 PM -0400"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %I:%M %p %z")
    except (ValueError, TypeError):
        pass
    # ISO format
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        pass
    # Date-only
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    return None


def _format_date(date_str: str | None) -> str:
    """Format a date string for human display (date only)."""
    dt = _parse_wb_date(date_str)
    if dt:
        return dt.strftime("%Y-%m-%d")
    return date_str or ""


def _format_datetime(date_str: str | None) -> str:
    """Format a date string for human display (date + time)."""
    dt = _parse_wb_date(date_str)
    if dt:
        return dt.strftime("%Y-%m-%d %I:%M %p")
    return date_str or ""


def _sort_date_key(item: dict[str, Any]) -> datetime:
    """Extract a comparable datetime for sorting (descending)."""
    dt = item.get("_sort_date")
    if dt is None:
        return datetime.min
    # Normalize timezone-aware → naive UTC for consistent comparison
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Slugify
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a name to a filename-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


# ---------------------------------------------------------------------------
# YAML helper
# ---------------------------------------------------------------------------

def _escape_yaml(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Household resolution
# ---------------------------------------------------------------------------

def _resolve_household(
    client: Any, contact: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Resolve household membership.

    Returns (member_contacts, household_info_or_None).
    """
    contact_type = contact.get("type", "")

    if contact_type == "Household":
        hh_id = contact.get("id")
        hh_name = contact.get("name", "")
        members = _fetch_household_members(client, contact)
        if not members:
            members = [contact]
        return members, {"id": hh_id, "name": hh_name}

    hh_ref = contact.get("household") or {}
    hh_id = hh_ref.get("id")
    if hh_id:
        hh_contact = client.get_contact(hh_id)
        hh_name = hh_contact.get("name", hh_ref.get("name", ""))
        members = _fetch_household_members(client, hh_contact)
        if not members:
            members = [contact]
        return members, {"id": hh_id, "name": hh_name}

    return [contact], None


def _fetch_household_members(
    client: Any, household_contact: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fetch individual member contacts from a household contact."""
    members: list[dict[str, Any]] = []
    for member_ref in household_contact.get("members", []):
        # Handle both {"contact": {"id": N}} and {"id": N} shapes
        inner = member_ref.get("contact", member_ref)
        member_id = inner.get("id") if isinstance(inner, dict) else None
        if member_id:
            members.append(client.get_contact(member_id))
    return members


# ---------------------------------------------------------------------------
# Activity fetching (with deduplication)
# ---------------------------------------------------------------------------

def _fetch_all_activity(
    client: Any,
    members: list[dict[str, Any]],
    user_map: dict[int, str],
    household_id: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch all activity types for every member, deduplicating by ID."""
    seen_notes: set[int] = set()
    seen_tasks: set[int] = set()
    seen_events: set[int] = set()
    seen_workflows: set[int] = set()
    seen_opps: set[int] = set()

    all_notes: list[dict[str, Any]] = []
    all_tasks: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    all_workflows: list[dict[str, Any]] = []
    all_opps: list[dict[str, Any]] = []

    member_ids = {m["id"] for m in members}
    if household_id is not None:
        member_ids.add(household_id)

    for member in members:
        member_id = member["id"]

        # Notes (with comments)
        for note in client.get_notes_with_comments(member_id):
            if note["id"] not in seen_notes:
                seen_notes.add(note["id"])
                all_notes.append(note)

        # Events (with comments)
        for event in client.get_events_with_comments(member_id):
            if event["id"] not in seen_events:
                seen_events.add(event["id"])
                all_events.append(event)

        # Workflows (with comments on steps)
        for wf in client.get_workflows_with_comments(member_id):
            if wf["id"] not in seen_workflows:
                seen_workflows.add(wf["id"])
                all_workflows.append(wf)

    # Tasks — API returns 0 with resource_type=contact, and defaults to
    # incomplete only.  Fetch both incomplete + completed, filter by linked_to.
    for completed_flag in ("false", "true"):
        for task in client.api_request("tasks", params={"completed": completed_flag}):
            linked_ids = {link["id"] for link in task.get("linked_to", []) if isinstance(link, dict)}
            if linked_ids & member_ids and task["id"] not in seen_tasks:
                seen_tasks.add(task["id"])
                task["comments"] = client.get_comments(task["id"], resource_type="task")
                all_tasks.append(task)

    # Opportunities — API ignores resource_id, so fetch all once and
    # filter client-side by linked_to contacts
    for opp in client.get_opportunities():
        linked_ids = {link["id"] for link in opp.get("linked_to", []) if isinstance(link, dict)}
        if linked_ids & member_ids and opp["id"] not in seen_opps:
            seen_opps.add(opp["id"])
            all_opps.append(opp)

    return {
        "notes": client.enhance_user_info(all_notes, user_map),
        "tasks": client.enhance_user_info(all_tasks, user_map),
        "events": client.enhance_user_info(all_events, user_map),
        "workflows": client.enhance_user_info(all_workflows, user_map),
        "opportunities": client.enhance_user_info(all_opps, user_map),
    }


# ---------------------------------------------------------------------------
# Timeline merging
# ---------------------------------------------------------------------------

def _merge_activity_timeline(
    activity: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Merge all activity types into a single reverse-chronological list."""
    timeline: list[dict[str, Any]] = []

    _DATE_FIELDS: dict[str, tuple[str, str]] = {
        "notes": ("note", "created_at"),
        "tasks": ("task", "due_date"),
        "events": ("event", "starts_at"),
        "workflows": ("workflow", "created_at"),
        "opportunities": ("opportunity", "target_close"),
    }

    for key, (activity_type, primary_date_field) in _DATE_FIELDS.items():
        for item in activity.get(key, []):
            sort_date = (
                _parse_wb_date(item.get(primary_date_field))
                or _parse_wb_date(item.get("created_at"))
            )
            timeline.append({
                "_activity_type": activity_type,
                "_sort_date": sort_date,
                **item,
            })

    timeline.sort(key=_sort_date_key, reverse=True)
    return timeline


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------

def _render_frontmatter(
    contact: dict[str, Any],
    hh_info: dict[str, Any] | None,
    members: list[dict[str, Any]],
) -> str:
    """Render QMD-compatible YAML frontmatter."""
    lines = ["---"]

    if contact.get("type") == "Household" and hh_info:
        title = hh_info.get("name", contact.get("name", "Unknown"))
    else:
        title = contact.get("name", "Unknown")

    lines.append(f'title: "{_escape_yaml(title)}"')
    lines.append('description: "Contact export from WealthBox CRM"')
    lines.append(f'date: "{datetime.now().strftime("%Y-%m-%d")}"')

    # Categories
    categories: list[str] = []
    if contact.get("contact_type"):
        categories.append(contact["contact_type"])
    if contact.get("type"):
        categories.append(contact["type"])
    if categories:
        lines.append("categories:")
        for cat in categories:
            lines.append(f"  - {cat}")

    # Tags
    tags = contact.get("tags", [])
    if tags:
        lines.append("tags:")
        for tag in tags:
            tag_name = tag.get("name", str(tag)) if isinstance(tag, dict) else str(tag)
            lines.append(f'  - "{_escape_yaml(tag_name)}"')

    lines.append(f'contact_id: {contact.get("id", "")}')
    if contact.get("contact_type"):
        lines.append(f'contact_type: "{_escape_yaml(contact["contact_type"])}"')
    if contact.get("type"):
        lines.append(f'type: "{_escape_yaml(contact["type"])}"')

    if hh_info:
        lines.append(f'household_id: {hh_info["id"]}')
        lines.append(f'household_name: "{_escape_yaml(hh_info["name"])}"')

    lines.append("---")
    return "\n".join(lines)


def _render_contact_info(members: list[dict[str, Any]]) -> str:
    """Render the contact information section."""
    parts: list[str] = []

    if len(members) > 1:
        parts.append("## Household Members\n")

    for member in members:
        name = member.get("name", "Unknown")
        if len(members) > 1:
            parts.append(f"### {name}\n")
        else:
            parts.append(f"# {name}\n")

        # Type / status line
        info_parts: list[str] = []
        if member.get("type"):
            info_parts.append(f'**Type:** {member["type"]}')
        if member.get("contact_type"):
            info_parts.append(f'**Contact Type:** {member["contact_type"]}')
        if member.get("status"):
            info_parts.append(f'**Status:** {member["status"]}')
        if info_parts:
            parts.append(" | ".join(info_parts))

        # Emails
        for email in member.get("email_addresses", []):
            addr = email.get("address", "")
            kind = email.get("kind", "")
            if addr:
                suffix = f" ({kind})" if kind else ""
                parts.append(f"**Email:** {addr}{suffix}")

        # Phones
        for phone in member.get("phone_numbers", []):
            addr = phone.get("address", "")
            kind = phone.get("kind", "")
            if addr:
                suffix = f" ({kind})" if kind else ""
                parts.append(f"**Phone:** {addr}{suffix}")

        # Birth date
        if member.get("birth_date"):
            parts.append(f'**Birth Date:** {member["birth_date"]}')

        # Job
        job_parts: list[str] = []
        if member.get("job_title"):
            job_parts.append(member["job_title"])
        company = member.get("company_name") or (
            member.get("company", {}).get("name", "") if isinstance(member.get("company"), dict) else ""
        )
        if company:
            job_parts.append(f"at {company}")
        if job_parts:
            parts.append(f'**Job Title:** {" ".join(job_parts)}')

        # Custom fields
        custom_fields = member.get("custom_fields", [])
        if custom_fields:
            parts.append("")
            heading = "### Custom Fields" if len(members) == 1 else "#### Custom Fields"
            parts.append(heading)
            for cf in custom_fields:
                if isinstance(cf, dict):
                    cf_name = cf.get("name", "")
                    cf_value = cf.get("value", "")
                    if cf_name and cf_value:
                        parts.append(f"- {cf_name}: {cf_value}")

        # Tags
        member_tags = member.get("tags", [])
        if member_tags:
            parts.append("")
            heading = "### Tags" if len(members) == 1 else "#### Tags"
            parts.append(heading)
            tag_names = [
                t.get("name", str(t)) if isinstance(t, dict) else str(t)
                for t in member_tags
            ]
            parts.append(", ".join(tag_names))

        parts.append("")

    return "\n".join(parts)


def _extract_body(body_field: Any) -> str:
    """Extract text from a body field that may be a string or a dict."""
    if isinstance(body_field, dict):
        # WealthBox returns {"html": "...", "text": "..."} for comment bodies
        return body_field.get("html", body_field.get("text", ""))
    if isinstance(body_field, str):
        return body_field
    return ""


def _render_comments(comments: list[dict[str, Any]]) -> str:
    """Render comments as blockquotes."""
    if not comments:
        return ""
    lines: list[str] = []
    for comment in comments:
        creator = comment.get("creator", "Unknown")
        date = _format_date(comment.get("created_at", ""))
        raw_body = _extract_body(comment.get("body", ""))
        body = _html_to_markdown(raw_body).strip() if raw_body else ""
        if body:
            date_part = f" ({date})" if date else ""
            lines.append(f"> **{creator}**{date_part}: {body}")
    return "\n".join(lines)


def _render_note(note: dict[str, Any]) -> str:
    date = _format_date(note.get("created_at", ""))
    creator = note.get("creator", "Unknown")

    lines = [f"### Note — {date}"]
    lines.append(f"*By: {creator}*")
    lines.append("")

    content = _extract_body(note.get("content", note.get("body", "")))
    if content:
        lines.append(_html_to_markdown(content))

    comments_str = _render_comments(note.get("comments", []))
    if comments_str:
        lines.append("")
        lines.append(comments_str)

    return "\n".join(lines)


def _render_task(task: dict[str, Any]) -> str:
    name = task.get("name", "Untitled Task")
    date = _format_date(task.get("due_date") or task.get("created_at", ""))
    completed = task.get("completed", False)

    check = " \u2713" if completed else ""
    lines = [f"### Task — {name}{check} — {date}"]

    meta_parts: list[str] = []
    if task.get("assigned_to"):
        meta_parts.append(f'Assigned to: {task["assigned_to"]}')
    if task.get("due_date"):
        meta_parts.append(f"Due: {_format_date(task['due_date'])}")
    status_label = "Completed" if completed else "Incomplete"
    meta_parts.append(f"Status: {status_label}")
    lines.append(f'*{" | ".join(meta_parts)}*')
    lines.append("")

    if task.get("description"):
        lines.append(task["description"])

    comments_str = _render_comments(task.get("comments", []))
    if comments_str:
        lines.append("")
        lines.append(comments_str)

    return "\n".join(lines)


def _render_event(event: dict[str, Any]) -> str:
    name = event.get("name", "Untitled Event")
    date = _format_date(event.get("starts_at") or event.get("created_at", ""))

    lines = [f"### Event — {name} — {date}"]

    meta_parts: list[str] = []
    starts = event.get("starts_at", "")
    ends = event.get("ends_at", "")
    if starts and ends:
        meta_parts.append(f"{_format_datetime(starts)} \u2013 {_format_datetime(ends)}")
    elif starts:
        meta_parts.append(_format_datetime(starts))
    if event.get("location"):
        meta_parts.append(f'Location: {event["location"]}')
    if meta_parts:
        lines.append(f'*{" | ".join(meta_parts)}*')
    lines.append("")

    if event.get("description"):
        lines.append(event["description"])

    comments_str = _render_comments(event.get("comments", []))
    if comments_str:
        lines.append("")
        lines.append(comments_str)

    return "\n".join(lines)


def _render_workflow(wf: dict[str, Any]) -> str:
    name = wf.get("name", "Untitled Workflow")
    status = wf.get("status", "")
    date = _format_date(wf.get("created_at", ""))

    status_label = f" ({status})" if status else ""
    lines = [f"### Workflow — {name}{status_label} — {date}"]

    steps = wf.get("workflow_steps", [])
    for i, step in enumerate(steps, 1):
        step_name = step.get("name", f"Step {i}")
        step_completed = step.get("completed", False)
        check = "\u2713 " if step_completed else ""
        lines.append(f"{i}. {check}{step_name}")

        step_comments = _render_comments(step.get("comments", []))
        if step_comments:
            for comment_line in step_comments.split("\n"):
                lines.append(f"   {comment_line}")

    return "\n".join(lines)


def _render_opportunity(opp: dict[str, Any]) -> str:
    name = opp.get("name", "Untitled Opportunity")
    date = _format_date(opp.get("target_close") or opp.get("created_at", ""))

    # Amount: prefer amounts array (API returns [{amount: "$100", kind: "Fee"}]),
    # fall back to top-level amount/value for backwards compatibility
    amount_str = ""
    amounts = opp.get("amounts", [])
    if amounts and isinstance(amounts, list):
        first = amounts[0].get("amount", "") if isinstance(amounts[0], dict) else ""
        if first:
            amount_str = f" ({first})"
    if not amount_str:
        amount = opp.get("amount") or opp.get("value")
        if amount:
            try:
                amount_str = f" (${float(amount):,.0f})"
            except (ValueError, TypeError):
                amount_str = f" ({amount})"

    lines = [f"### Opportunity — {name}{amount_str} — {date}"]

    meta_parts: list[str] = []
    stage = opp.get("stage_name") or opp.get("stage")
    if stage:
        if isinstance(stage, dict):
            stage = stage.get("name", "")
        # Skip integer stage IDs — no stage-name lookup available
        if not isinstance(stage, int):
            meta_parts.append(f"Stage: {stage}")
    if opp.get("target_close"):
        meta_parts.append(f"Close Date: {_format_date(opp['target_close'])}")
    if meta_parts:
        lines.append(f'*{" | ".join(meta_parts)}*')

    return "\n".join(lines)


def _render_timeline(timeline: list[dict[str, Any]]) -> str:
    """Render the full unified activity timeline."""
    if not timeline:
        return ""

    _RENDERERS = {
        "note": _render_note,
        "task": _render_task,
        "event": _render_event,
        "workflow": _render_workflow,
        "opportunity": _render_opportunity,
    }

    parts = ["# Activity\n"]
    for item in timeline:
        renderer = _RENDERERS.get(item.get("_activity_type", ""))
        if renderer:
            parts.append("---\n")
            parts.append(renderer(item))
            parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def export_contact_to_markdown(client: Any, contact_id: int) -> str:
    """Export a contact (and its household) to QMD-compatible markdown.

    Returns the full markdown string.
    """
    contact = client.get_contact(contact_id)

    members, hh_info = _resolve_household(client, contact)

    user_map = client.make_user_map("name")

    hh_id = hh_info["id"] if hh_info else None
    activity = _fetch_all_activity(client, members, user_map, household_id=hh_id)

    timeline = _merge_activity_timeline(activity)

    parts: list[str] = []
    parts.append(_render_frontmatter(contact, hh_info, members))
    parts.append("")
    parts.append(_render_contact_info(members))

    timeline_str = _render_timeline(timeline)
    if timeline_str:
        parts.append(timeline_str)

    return "\n".join(parts) + "\n"
