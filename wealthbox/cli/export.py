"""Contact export to markdown for the WealthBox CLI."""

from __future__ import annotations

import json as _json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any


# ---------------------------------------------------------------------------
# Export cache for multi-contact exports
# ---------------------------------------------------------------------------


@dataclass
class ExportCache:
    """Cache for firm-wide data to reduce API calls across multiple exports.

    Usage:
        cache = ExportCache()
        for contact_id in contact_ids:
            markdown = export_contact_to_markdown(client, contact_id, cache=cache)
    """

    user_map: dict[int, str] | None = None
    all_tasks: list[dict[str, Any]] | None = None
    all_opportunities: list[dict[str, Any]] | None = None
    _task_comments: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def get_user_map(self, client: Any) -> dict[int, str]:
        """Get user map, fetching once and caching."""
        if self.user_map is None:
            self.user_map = client.make_user_map("name")
        return self.user_map

    def get_all_tasks(self, client: Any) -> list[dict[str, Any]]:
        """Get all tasks (completed + incomplete), fetching once and caching."""
        if self.all_tasks is None:
            tasks: list[dict[str, Any]] = []
            for completed_flag in ("false", "true"):
                tasks.extend(
                    client.api_request("tasks", params={"completed": completed_flag})
                )
            self.all_tasks = tasks
        return self.all_tasks

    def get_task_comments(self, client: Any, task_id: int) -> list[dict[str, Any]]:
        """Get comments for a task, caching to avoid duplicate fetches."""
        if task_id not in self._task_comments:
            self._task_comments[task_id] = client.get_comments(
                task_id, resource_type="task"
            )
        return self._task_comments[task_id]

    def get_all_opportunities(self, client: Any) -> list[dict[str, Any]]:
        """Get all opportunities, fetching once and caching."""
        if self.all_opportunities is None:
            self.all_opportunities = client.get_opportunities()
        return self.all_opportunities


# ---------------------------------------------------------------------------
# Export metadata for incremental updates
# ---------------------------------------------------------------------------


@dataclass
class ExportMetadata:
    """Tracks export state for incremental updates.

    Stores the last export timestamp and a mapping of contact IDs to their
    output filenames so incremental exports can skip unchanged contacts.
    """

    last_export: datetime | None = None
    contact_files: dict[int, str] = field(default_factory=dict)
    version: int = 1

    META_FILENAME = ".export-meta.json"

    @classmethod
    def load(cls, output_dir: str) -> ExportMetadata:
        """Load metadata from .export-meta.json in the output directory."""
        path = os.path.join(output_dir, cls.META_FILENAME)
        if not os.path.exists(path):
            return cls()
        try:
            with open(path) as f:
                data = _json.load(f)
            last_export = None
            if data.get("last_export"):
                last_export = datetime.fromisoformat(data["last_export"])
            contact_files = {
                int(k): v for k, v in data.get("contact_files", {}).items()
            }
            return cls(
                last_export=last_export,
                contact_files=contact_files,
                version=data.get("version", 1),
            )
        except (OSError, ValueError, KeyError):
            return cls()

    def save(self, output_dir: str) -> None:
        """Save metadata to .export-meta.json in the output directory."""
        path = os.path.join(output_dir, self.META_FILENAME)
        data = {
            "last_export": self.last_export.isoformat() if self.last_export else None,
            "version": self.version,
            "contact_files": {str(k): v for k, v in self.contact_files.items()},
        }
        with open(path, "w") as f:
            _json.dump(data, f, indent=2)
            f.write("\n")


# ---------------------------------------------------------------------------
# Dirty-contact detection for incremental exports
# ---------------------------------------------------------------------------


def _is_after(date_str: str | None, threshold: datetime) -> bool:
    """Check if a WealthBox date string is after the given threshold."""
    dt = _parse_wb_date(date_str)
    if dt is None:
        return False
    # Normalize both to UTC-naive for consistent comparison
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    threshold_naive = threshold
    if threshold_naive.tzinfo is not None:
        threshold_naive = threshold_naive.astimezone(timezone.utc).replace(tzinfo=None)
    return dt > threshold_naive


def _collect_linked_ids(item: dict[str, Any]) -> set[int]:
    """Extract contact IDs from an item's linked_to list."""
    ids: set[int] = set()
    for link in item.get("linked_to", []):
        if isinstance(link, dict) and "id" in link:
            ids.add(link["id"])
    return ids


def find_dirty_contacts(
    client: Any,
    last_export: datetime | None,
    cache: ExportCache,
    comment_lookback_days: int = 30,
) -> set[int] | None:
    """Identify contacts that need re-export since last_export.

    Returns a set of contact IDs that have changed, or None to signal
    that all contacts should be exported (first run).
    """
    if last_export is None:
        return None  # First run — export everything

    dirty: set[int] = set()

    # 1. Contacts updated since last export (API-supported filter)
    updated_contacts = client.get_contacts(
        filters={"updated_since": last_export.isoformat()}
    )
    for c in updated_contacts:
        dirty.add(c["id"])
        # If contact belongs to a household, mark it dirty too
        hh = c.get("household")
        if isinstance(hh, dict) and hh.get("id"):
            dirty.add(hh["id"])

    # 2. Tasks created since last export
    for task in cache.get_all_tasks(client):
        if _is_after(task.get("created_at"), last_export):
            dirty.update(_collect_linked_ids(task))

    # 3. Opportunities created since last export
    for opp in cache.get_all_opportunities(client):
        if _is_after(opp.get("created_at"), last_export):
            dirty.update(_collect_linked_ids(opp))

    # 4. Comments on recent tasks (within lookback window)
    lookback_cutoff = last_export - timedelta(days=comment_lookback_days)
    for task in cache.get_all_tasks(client):
        task_date = _parse_wb_date(task.get("created_at"))
        if task_date is None:
            continue
        # Normalize for comparison
        if task_date.tzinfo is not None:
            task_date = task_date.astimezone(timezone.utc).replace(tzinfo=None)
        lookback_naive = lookback_cutoff
        if lookback_naive.tzinfo is not None:
            lookback_naive = lookback_naive.astimezone(timezone.utc).replace(tzinfo=None)
        if task_date < lookback_naive:
            continue
        # Check comments on this recent task
        comments = cache.get_task_comments(client, task["id"])
        for comment in comments:
            if _is_after(comment.get("created_at"), last_export):
                dirty.update(_collect_linked_ids(task))
                break  # One new comment is enough to mark dirty

    return dirty


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
    cache: ExportCache | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch all activity types for every member, deduplicating by ID.

    If cache is provided, uses cached tasks and opportunities instead of
    re-fetching from the API.
    """
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
    # Use cache if available to avoid re-fetching for each contact.
    if cache is not None:
        tasks_source = cache.get_all_tasks(client)
    else:
        tasks_source = []
        for completed_flag in ("false", "true"):
            tasks_source.extend(
                client.api_request("tasks", params={"completed": completed_flag})
            )

    for task in tasks_source:
        linked_ids = {link["id"] for link in task.get("linked_to", []) if isinstance(link, dict)}
        if linked_ids & member_ids and task["id"] not in seen_tasks:
            seen_tasks.add(task["id"])
            # Make a copy to avoid mutating cached data
            task_copy = dict(task)
            if cache is not None:
                task_copy["comments"] = cache.get_task_comments(client, task["id"])
            else:
                task_copy["comments"] = client.get_comments(task["id"], resource_type="task")
            all_tasks.append(task_copy)

    # Opportunities — API ignores resource_id, so fetch all once and
    # filter client-side by linked_to contacts
    if cache is not None:
        opps_source = cache.get_all_opportunities(client)
    else:
        opps_source = client.get_opportunities()

    for opp in opps_source:
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

        # Nickname
        if member.get("nickname"):
            parts.append(f'**Nickname:** {member["nickname"]}')

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


def _render_note(
    note: dict[str, Any],
    workspace_id: int | None = None,
    contact_id: int | None = None,
) -> str:
    date = _format_date(note.get("created_at", ""))
    creator = note.get("creator", "Unknown")

    lines = [f"### Note — {date}"]

    # Add Wealthbox link if workspace_id provided
    note_id = note.get("id")
    if workspace_id and contact_id and note_id:
        wb_url = f"https://www.crmworkspace.com/{workspace_id}/contacts/{contact_id}#note-{note_id}"
        lines.append(f"*[View in Wealthbox]({wb_url})*")

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


def _render_task(
    task: dict[str, Any],
    workspace_id: int | None = None,
    contact_id: int | None = None,
) -> str:
    name = task.get("name", "Untitled Task")
    date = _format_date(task.get("due_date") or task.get("created_at", ""))
    completed = task.get("completed", False)

    check = " \u2713" if completed else ""
    lines = [f"### Task — {name}{check} — {date}"]

    # Add Wealthbox link if workspace_id provided
    task_id = task.get("id")
    if workspace_id and task_id:
        wb_url = f"https://www.crmworkspace.com/{workspace_id}/tasks?task_id={task_id}"
        lines.append(f"*[View in Wealthbox]({wb_url})*")

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


def _render_event(
    event: dict[str, Any],
    workspace_id: int | None = None,
    contact_id: int | None = None,
) -> str:
    name = event.get("name", "Untitled Event")
    date = _format_date(event.get("starts_at") or event.get("created_at", ""))

    lines = [f"### Event — {name} — {date}"]

    # Add Wealthbox link if workspace_id provided
    event_id = event.get("id")
    if workspace_id and event_id:
        wb_url = f"https://www.crmworkspace.com/{workspace_id}/events/{event_id}"
        lines.append(f"*[View in Wealthbox]({wb_url})*")

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


def _render_workflow(
    wf: dict[str, Any],
    workspace_id: int | None = None,
    contact_id: int | None = None,
) -> str:
    name = wf.get("name", "Untitled Workflow")
    status = wf.get("status", "")
    date = _format_date(wf.get("created_at", ""))

    status_label = f" ({status})" if status else ""
    lines = [f"### Workflow — {name}{status_label} — {date}"]

    # Add Wealthbox link if workspace_id provided
    wf_id = wf.get("id")
    if workspace_id and wf_id:
        wb_url = f"https://www.crmworkspace.com/{workspace_id}/workflows/{wf_id}"
        lines.append(f"*[View in Wealthbox]({wb_url})*")

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


def _render_opportunity(
    opp: dict[str, Any],
    workspace_id: int | None = None,
    contact_id: int | None = None,
) -> str:
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

    # Add Wealthbox link if workspace_id provided
    opp_id = opp.get("id")
    if workspace_id and opp_id:
        wb_url = f"https://www.crmworkspace.com/{workspace_id}/opportunities/{opp_id}"
        lines.append(f"*[View in Wealthbox]({wb_url})*")

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


def _render_timeline(
    timeline: list[dict[str, Any]],
    workspace_id: int | None = None,
    contact_id: int | None = None,
) -> str:
    """Render the full unified activity timeline.

    Args:
        timeline: List of activity items to render.
        workspace_id: Optional Wealthbox workspace ID for generating links.
        contact_id: Optional contact ID for note links.
    """
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
            parts.append(renderer(item, workspace_id=workspace_id, contact_id=contact_id))
            parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def export_contact_to_markdown(
    client: Any,
    contact_id: int,
    cache: ExportCache | None = None,
    workspace_id: int | None = None,
) -> str:
    """Export a contact (and its household) to QMD-compatible markdown.

    Args:
        client: WealthBox client instance.
        contact_id: ID of the contact to export.
        cache: Optional ExportCache to reuse firm-wide data across exports.
            Pass the same cache instance when exporting multiple contacts
            to significantly reduce API calls.
        workspace_id: Optional Wealthbox workspace ID. If provided, activity
            items will include clickable links to view them in Wealthbox.
            Example: 15708 for Dock Street.

    Returns the full markdown string.
    """
    contact = client.get_contact(contact_id)

    members, hh_info = _resolve_household(client, contact)

    # Use cached user_map if available
    if cache is not None:
        user_map = cache.get_user_map(client)
    else:
        user_map = client.make_user_map("name")

    hh_id = hh_info["id"] if hh_info else None
    activity = _fetch_all_activity(
        client, members, user_map, household_id=hh_id, cache=cache
    )

    timeline = _merge_activity_timeline(activity)

    parts: list[str] = []
    parts.append(_render_frontmatter(contact, hh_info, members))
    parts.append("")
    parts.append(_render_contact_info(members))

    timeline_str = _render_timeline(
        timeline, workspace_id=workspace_id, contact_id=contact_id
    )
    if timeline_str:
        parts.append(timeline_str)

    return "\n".join(parts) + "\n"
