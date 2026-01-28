"""Tests for the contact export command."""

from __future__ import annotations

import json

import pytest
import responses
from click.testing import CliRunner

from wealthbox.cli.export import (
    _escape_yaml,
    _extract_body,
    _fetch_household_members,
    _format_date,
    _format_datetime,
    _html_to_markdown,
    _merge_activity_timeline,
    _parse_wb_date,
    _render_comments,
    _render_contact_info,
    _render_event,
    _render_frontmatter,
    _render_note,
    _render_opportunity,
    _render_task,
    _render_timeline,
    _render_workflow,
    _slugify,
)
from wealthbox.cli.main import cli


BASE_URL = "https://api.crmworkspace.com/v1/"


# ---------------------------------------------------------------------------
# Unit tests: _html_to_markdown
# ---------------------------------------------------------------------------


class TestHtmlToMarkdown:
    def test_plain_text_passthrough(self):
        assert _html_to_markdown("Hello world") == "Hello world"

    def test_empty_string(self):
        assert _html_to_markdown("") == ""

    def test_none_returns_empty(self):
        assert _html_to_markdown(None) == ""

    def test_bold(self):
        assert _html_to_markdown("<b>bold</b>") == "**bold**"

    def test_strong(self):
        assert _html_to_markdown("<strong>strong</strong>") == "**strong**"

    def test_italic(self):
        assert _html_to_markdown("<i>italic</i>") == "*italic*"

    def test_em(self):
        assert _html_to_markdown("<em>emphasis</em>") == "*emphasis*"

    def test_br_newline(self):
        assert _html_to_markdown("line1<br>line2") == "line1\nline2"

    def test_br_self_closing(self):
        assert _html_to_markdown("line1<br/>line2") == "line1\nline2"

    def test_paragraph(self):
        result = _html_to_markdown("<p>First paragraph</p><p>Second paragraph</p>")
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_link_as_reference(self):
        result = _html_to_markdown('<a href="https://example.com">Click here</a>')
        assert "Click here [1]" in result
        assert "[1]: https://example.com" in result

    def test_multiple_links(self):
        html = '<a href="https://a.com">A</a> and <a href="https://b.com">B</a>'
        result = _html_to_markdown(html)
        assert "A [1]" in result
        assert "B [2]" in result
        assert "[1]: https://a.com" in result
        assert "[2]: https://b.com" in result

    def test_unordered_list(self):
        result = _html_to_markdown("<ul><li>One</li><li>Two</li></ul>")
        assert "- One" in result
        assert "- Two" in result

    def test_nested_tags(self):
        result = _html_to_markdown("<b><i>bold italic</i></b>")
        assert "***bold italic***" in result or "**" in result


# ---------------------------------------------------------------------------
# Unit tests: date parsing
# ---------------------------------------------------------------------------


class TestDateParsing:
    def test_wb_format(self):
        dt = _parse_wb_date("2023-06-21 03:32 PM -0400")
        assert dt is not None
        assert dt.year == 2023
        assert dt.month == 6
        assert dt.day == 21

    def test_iso_format(self):
        dt = _parse_wb_date("2023-06-21T15:32:00")
        assert dt is not None
        assert dt.year == 2023

    def test_date_only(self):
        dt = _parse_wb_date("2023-06-21")
        assert dt is not None
        assert dt.day == 21

    def test_none_returns_none(self):
        assert _parse_wb_date(None) is None

    def test_empty_returns_none(self):
        assert _parse_wb_date("") is None

    def test_invalid_returns_none(self):
        assert _parse_wb_date("not-a-date") is None

    def test_format_date(self):
        assert _format_date("2023-06-21 03:32 PM -0400") == "2023-06-21"

    def test_format_date_none(self):
        assert _format_date(None) == ""

    def test_format_datetime(self):
        result = _format_datetime("2023-06-21 03:32 PM -0400")
        assert "2023-06-21" in result
        assert "PM" in result


# ---------------------------------------------------------------------------
# Unit tests: _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_simple_name(self):
        assert _slugify("John Smith") == "john-smith"

    def test_special_chars(self):
        assert _slugify("O'Brien, Jr.") == "obrien-jr"

    def test_extra_spaces(self):
        assert _slugify("  John   Smith  ") == "john-smith"

    def test_already_slug(self):
        assert _slugify("john-smith") == "john-smith"

    def test_unicode(self):
        result = _slugify("José García")
        assert "jos" in result


# ---------------------------------------------------------------------------
# Unit tests: _render_frontmatter
# ---------------------------------------------------------------------------


class TestRenderFrontmatter:
    def test_person_no_household(self):
        contact = {"id": 100, "name": "John Smith", "type": "Person", "contact_type": "Client"}
        result = _render_frontmatter(contact, None, [contact])
        assert '---' in result
        assert 'title: "John Smith"' in result
        assert "contact_id: 100" in result
        assert "household_id" not in result

    def test_person_with_household(self):
        contact = {"id": 100, "name": "John Smith", "type": "Person"}
        hh_info = {"id": 200, "name": "Smith, John & Jane"}
        result = _render_frontmatter(contact, hh_info, [contact])
        assert 'title: "John Smith"' in result
        assert "household_id: 200" in result
        assert 'household_name: "Smith, John & Jane"' in result

    def test_household_type(self):
        contact = {"id": 200, "name": "Smith Household", "type": "Household"}
        hh_info = {"id": 200, "name": "Smith Household"}
        result = _render_frontmatter(contact, hh_info, [])
        assert 'title: "Smith Household"' in result

    def test_tags_in_frontmatter(self):
        contact = {"id": 1, "name": "X", "tags": [{"name": "VIP"}, {"name": "High Net Worth"}]}
        result = _render_frontmatter(contact, None, [contact])
        assert '"VIP"' in result
        assert '"High Net Worth"' in result

    def test_categories(self):
        contact = {"id": 1, "name": "X", "type": "Person", "contact_type": "Client"}
        result = _render_frontmatter(contact, None, [contact])
        assert "  - Client" in result
        assert "  - Person" in result


# ---------------------------------------------------------------------------
# Unit tests: _render_contact_info
# ---------------------------------------------------------------------------


class TestRenderContactInfo:
    def test_single_person(self):
        member = {
            "name": "John Smith",
            "type": "Person",
            "contact_type": "Client",
            "email_addresses": [{"address": "john@example.com", "kind": "Work"}],
            "phone_numbers": [{"address": "555-1234", "kind": "Mobile"}],
            "birth_date": "1980-05-15",
        }
        result = _render_contact_info([member])
        assert "# John Smith" in result
        assert "**Email:** john@example.com (Work)" in result
        assert "**Phone:** 555-1234 (Mobile)" in result
        assert "**Birth Date:** 1980-05-15" in result

    def test_multiple_members(self):
        m1 = {"name": "John Smith", "type": "Person"}
        m2 = {"name": "Jane Smith", "type": "Person"}
        result = _render_contact_info([m1, m2])
        assert "## Household Members" in result
        assert "### John Smith" in result
        assert "### Jane Smith" in result

    def test_custom_fields(self):
        member = {
            "name": "John",
            "custom_fields": [{"name": "Family", "value": "Smith"}],
        }
        result = _render_contact_info([member])
        assert "### Custom Fields" in result
        assert "- Family: Smith" in result

    def test_tags(self):
        member = {
            "name": "John",
            "tags": [{"name": "VIP"}, {"name": "HNW"}],
        }
        result = _render_contact_info([member])
        assert "### Tags" in result
        assert "VIP, HNW" in result

    def test_job_title_with_company(self):
        member = {
            "name": "John",
            "job_title": "CEO",
            "company_name": "Acme Corp",
        }
        result = _render_contact_info([member])
        assert "**Job Title:** CEO at Acme Corp" in result

    def test_no_optional_fields(self):
        member = {"name": "Minimal"}
        result = _render_contact_info([member])
        assert "# Minimal" in result
        assert "Email" not in result
        assert "Phone" not in result


# ---------------------------------------------------------------------------
# Unit tests: _render_comments
# ---------------------------------------------------------------------------


class TestRenderComments:
    def test_with_comments(self):
        comments = [
            {"creator": "Spencer", "created_at": "2026-01-27", "body": "Looks good."},
            {"creator": "Jane", "created_at": "2026-01-28", "body": "Agreed."},
        ]
        result = _render_comments(comments)
        assert "> **Spencer** (2026-01-27): Looks good." in result
        assert "> **Jane** (2026-01-28): Agreed." in result

    def test_empty_comments(self):
        assert _render_comments([]) == ""

    def test_comment_with_empty_body(self):
        comments = [{"creator": "X", "body": ""}]
        result = _render_comments(comments)
        assert result == ""

    def test_comment_with_dict_body(self):
        """WealthBox returns body as {"html": "...", "text": "..."}."""
        comments = [
            {
                "creator": "Spencer",
                "created_at": "2026-01-27",
                "body": {"html": "<div>Great call.</div>", "text": "Great call."},
            },
        ]
        result = _render_comments(comments)
        assert "> **Spencer** (2026-01-27): Great call." in result

    def test_comment_with_dict_body_html_tags(self):
        comments = [
            {
                "creator": "X",
                "created_at": "2026-01-01",
                "body": {"html": "<b>Important</b> update", "text": "Important update"},
            },
        ]
        result = _render_comments(comments)
        assert "**Important** update" in result


class TestExtractBody:
    def test_string_passthrough(self):
        assert _extract_body("hello") == "hello"

    def test_dict_prefers_html(self):
        assert _extract_body({"html": "<b>hi</b>", "text": "hi"}) == "<b>hi</b>"

    def test_dict_falls_back_to_text(self):
        assert _extract_body({"text": "hi"}) == "hi"

    def test_empty_dict(self):
        assert _extract_body({}) == ""

    def test_none(self):
        assert _extract_body(None) == ""

    def test_empty_string(self):
        assert _extract_body("") == ""


# ---------------------------------------------------------------------------
# Unit tests: _render_note
# ---------------------------------------------------------------------------


class TestRenderNote:
    def test_basic_note(self):
        note = {
            "created_at": "2026-01-26",
            "creator": "Spencer Ogden",
            "content": "Called client about Q4.",
            "comments": [],
        }
        result = _render_note(note)
        assert "### Note — 2026-01-26" in result
        assert "*By: Spencer Ogden*" in result
        assert "Called client about Q4." in result

    def test_note_with_comments(self):
        note = {
            "created_at": "2026-01-26",
            "creator": "Spencer",
            "content": "Some note",
            "comments": [
                {"creator": "Jane", "created_at": "2026-01-27", "body": "Follow up needed."},
            ],
        }
        result = _render_note(note)
        assert "> **Jane** (2026-01-27): Follow up needed." in result

    def test_note_with_html_content(self):
        note = {
            "created_at": "2026-01-26",
            "creator": "X",
            "content": "<b>Important</b> note",
            "comments": [],
        }
        result = _render_note(note)
        assert "**Important** note" in result


# ---------------------------------------------------------------------------
# Unit tests: _render_task
# ---------------------------------------------------------------------------


class TestRenderTask:
    def test_incomplete_task(self):
        task = {
            "name": "Follow up call",
            "due_date": "2026-02-01",
            "assigned_to": "Spencer Ogden",
            "completed": False,
            "description": "Call about rebalancing.",
            "comments": [],
        }
        result = _render_task(task)
        assert "### Task — Follow up call — 2026-02-01" in result
        assert "Assigned to: Spencer Ogden" in result
        assert "Status: Incomplete" in result
        assert "Call about rebalancing." in result
        assert "\u2713" not in result.split("\n")[0]

    def test_completed_task(self):
        task = {
            "name": "Annual review",
            "due_date": "2026-01-30",
            "completed": True,
            "comments": [],
        }
        result = _render_task(task)
        assert "\u2713" in result.split("\n")[0]
        assert "Status: Completed" in result

    def test_task_with_comments(self):
        task = {
            "name": "Task",
            "due_date": "2026-01-01",
            "completed": False,
            "comments": [
                {"creator": "Admin", "created_at": "2026-01-02", "body": "Done."},
            ],
        }
        result = _render_task(task)
        assert "> **Admin** (2026-01-02): Done." in result


# ---------------------------------------------------------------------------
# Unit tests: _render_event
# ---------------------------------------------------------------------------


class TestRenderEvent:
    def test_basic_event(self):
        event = {
            "name": "Client Meeting",
            "starts_at": "2026-01-20 09:00 AM -0500",
            "ends_at": "2026-01-20 10:00 AM -0500",
            "location": "Office",
            "description": "Annual review.",
            "comments": [],
        }
        result = _render_event(event)
        assert "### Event — Client Meeting — 2026-01-20" in result
        assert "Location: Office" in result
        assert "Annual review." in result

    def test_event_without_location(self):
        event = {
            "name": "Call",
            "starts_at": "2026-01-20",
            "comments": [],
        }
        result = _render_event(event)
        assert "Location" not in result


# ---------------------------------------------------------------------------
# Unit tests: _render_workflow
# ---------------------------------------------------------------------------


class TestRenderWorkflow:
    def test_workflow_with_steps(self):
        wf = {
            "name": "New Client Onboarding",
            "status": "completed",
            "created_at": "2026-01-01",
            "workflow_steps": [
                {"name": "Welcome email", "completed": True, "comments": []},
                {"name": "Initial meeting", "completed": True, "comments": []},
                {"name": "Portfolio transfer", "completed": False, "comments": []},
            ],
        }
        result = _render_workflow(wf)
        assert "### Workflow — New Client Onboarding (completed) — 2026-01-01" in result
        assert "1. \u2713 Welcome email" in result
        assert "2. \u2713 Initial meeting" in result
        assert "3. Portfolio transfer" in result

    def test_workflow_step_comments(self):
        wf = {
            "name": "WF",
            "status": "active",
            "created_at": "2026-01-01",
            "workflow_steps": [
                {
                    "name": "Step A",
                    "completed": True,
                    "comments": [
                        {"creator": "Spencer", "created_at": "2026-01-02", "body": "Sent packet"},
                    ],
                },
            ],
        }
        result = _render_workflow(wf)
        assert "   > **Spencer** (2026-01-02): Sent packet" in result


# ---------------------------------------------------------------------------
# Unit tests: _render_opportunity
# ---------------------------------------------------------------------------


class TestRenderOpportunity:
    def test_basic_opportunity(self):
        opp = {
            "name": "Retirement Planning",
            "amount": 500000,
            "stage_name": "Closed Won",
            "target_close": "2026-06-01",
        }
        result = _render_opportunity(opp)
        assert "### Opportunity — Retirement Planning ($500,000) — 2026-06-01" in result
        assert "Stage: Closed Won" in result
        assert "Close Date: 2026-06-01" in result

    def test_opportunity_no_amount(self):
        opp = {"name": "Lead", "target_close": "2026-03-01"}
        result = _render_opportunity(opp)
        assert "### Opportunity — Lead — 2026-03-01" in result
        assert "$" not in result

    def test_opportunity_with_stage_dict(self):
        opp = {
            "name": "Deal",
            "stage": {"name": "Proposal"},
            "target_close": "2026-01-01",
        }
        result = _render_opportunity(opp)
        assert "Stage: Proposal" in result

    def test_stage_integer_omitted(self):
        """Bug 3: stage is an int ID (e.g. 144686) — should not render."""
        opp = {"name": "Deal", "stage": 144686, "target_close": "2026-01-01"}
        result = _render_opportunity(opp)
        assert "Stage" not in result
        assert "144686" not in result

    def test_amounts_array(self):
        """Bug 4: amount lives in amounts array, not top-level amount."""
        opp = {
            "name": "Fee Review",
            "amounts": [{"amount": "$500", "kind": "Fee"}],
            "target_close": "2026-03-01",
        }
        result = _render_opportunity(opp)
        assert "($500)" in result

    def test_amounts_array_multiple(self):
        """Bug 4: when multiple amounts, first entry is used."""
        opp = {
            "name": "Multi",
            "amounts": [
                {"amount": "$1,000", "kind": "AUM"},
                {"amount": "$200", "kind": "Fee"},
            ],
        }
        result = _render_opportunity(opp)
        assert "($1,000)" in result

    def test_fallback_to_top_level_amount(self):
        """amounts array empty → fall back to top-level amount."""
        opp = {"name": "Old", "amount": 250000, "target_close": "2026-01-01"}
        result = _render_opportunity(opp)
        assert "($250,000)" in result

    def test_target_close_date(self):
        """Bug 5: date field is target_close, not close_date."""
        opp = {"name": "Opp", "target_close": "2026-06-15"}
        result = _render_opportunity(opp)
        assert "2026-06-15" in result
        assert "Close Date: 2026-06-15" in result


# ---------------------------------------------------------------------------
# Unit tests: _render_timeline
# ---------------------------------------------------------------------------


class TestRenderTimeline:
    def test_empty_timeline(self):
        assert _render_timeline([]) == ""

    def test_mixed_timeline(self):
        timeline = [
            {"_activity_type": "note", "_sort_date": None, "created_at": "2026-01-26", "creator": "X", "content": "A note", "comments": []},
            {"_activity_type": "task", "_sort_date": None, "name": "Do it", "due_date": "2026-01-25", "completed": False, "comments": []},
        ]
        result = _render_timeline(timeline)
        assert "# Activity" in result
        assert "### Note" in result
        assert "### Task" in result
        assert "---" in result


# ---------------------------------------------------------------------------
# Unit tests: sort by date
# ---------------------------------------------------------------------------


class TestSortByDate:
    def test_reverse_chronological(self):
        activity = {
            "notes": [
                {"id": 1, "created_at": "2026-01-20"},
                {"id": 2, "created_at": "2026-01-25"},
            ],
            "tasks": [],
            "events": [],
            "workflows": [],
            "opportunities": [],
        }
        timeline = _merge_activity_timeline(activity)
        # Most recent first
        assert timeline[0]["id"] == 2
        assert timeline[1]["id"] == 1

    def test_items_without_dates_at_end(self):
        activity = {
            "notes": [
                {"id": 1, "created_at": "2026-01-20"},
                {"id": 2},  # No date
            ],
            "tasks": [],
            "events": [],
            "workflows": [],
            "opportunities": [],
        }
        timeline = _merge_activity_timeline(activity)
        assert timeline[0]["id"] == 1
        assert timeline[1]["id"] == 2

    def test_mixed_activity_types_sorted(self):
        activity = {
            "notes": [{"id": 1, "created_at": "2026-01-10"}],
            "tasks": [{"id": 2, "due_date": "2026-01-20"}],
            "events": [{"id": 3, "starts_at": "2026-01-15"}],
            "workflows": [],
            "opportunities": [],
        }
        timeline = _merge_activity_timeline(activity)
        types = [t["_activity_type"] for t in timeline]
        assert types == ["task", "event", "note"]


# ---------------------------------------------------------------------------
# Integration tests: CLI export command
# ---------------------------------------------------------------------------

def _register_users_endpoint():
    """Register the /users endpoint that make_user_map calls."""
    responses.add(
        responses.GET,
        f"{BASE_URL}users",
        json={
            "users": [{"id": 10, "name": "Spencer Ogden", "email": "spencer@example.com"}],
            "meta": {"total_pages": 1},
        },
        status=200,
    )


def _register_single_contact(contact_id, contact_data):
    """Register a GET /contacts/<id> endpoint."""
    responses.add(
        responses.GET,
        f"{BASE_URL}contacts/{contact_id}",
        json=contact_data,
        status=200,
    )


def _register_empty_activity(member_id):
    """Register empty activity endpoints for a member.

    Call order: per-member loop fetches notes, events, workflows(x3).
    After the loop: tasks(x2 for completed=false/true), opportunities(x1).
    """
    # Notes (uses status_updates key)
    responses.add(
        responses.GET,
        f"{BASE_URL}notes",
        json={"status_updates": [], "meta": {"total_pages": 1}},
        status=200,
    )
    # Events
    responses.add(
        responses.GET,
        f"{BASE_URL}events",
        json={"events": [], "meta": {"total_pages": 1}},
        status=200,
    )
    # Workflows (active, completed, scheduled)
    for _ in range(3):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows",
            json={"workflows": [], "meta": {"total_pages": 1}},
            status=200,
        )
    # Tasks (completed=false + completed=true, fetched once after member loop)
    for _ in range(2):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200,
        )
    # Opportunities
    responses.add(
        responses.GET,
        f"{BASE_URL}opportunities",
        json={"opportunities": [], "meta": {"total_pages": 1}},
        status=200,
    )


class TestExportCommand:
    @responses.activate
    def test_export_stdout(self, runner, mock_token):
        contact = {
            "id": 12345,
            "name": "John Smith",
            "type": "Person",
            "contact_type": "Client",
            "email_addresses": [{"address": "john@example.com", "kind": "Work"}],
        }
        _register_single_contact(12345, contact)
        _register_users_endpoint()
        _register_empty_activity(12345)

        result = runner.invoke(cli, ["contacts", "export", "12345", "--stdout"])
        assert result.exit_code == 0, result.output
        assert 'title: "John Smith"' in result.output
        assert "# John Smith" in result.output
        assert "**Email:** john@example.com (Work)" in result.output

    @responses.activate
    def test_export_to_file(self, runner, mock_token, tmp_path):
        contact = {"id": 100, "name": "Jane Doe", "type": "Person"}
        _register_single_contact(100, contact)
        _register_users_endpoint()
        _register_empty_activity(100)

        out_file = str(tmp_path / "test-export.md")
        result = runner.invoke(cli, ["contacts", "export", "100", "-o", out_file])
        assert result.exit_code == 0, result.output
        assert f"Exported to {out_file}" in result.output

        with open(out_file) as f:
            content = f.read()
        assert 'title: "Jane Doe"' in content

    @responses.activate
    def test_export_auto_filename(self, runner, mock_token, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        contact = {"id": 42, "name": "Bob Jones", "type": "Person"}
        _register_single_contact(42, contact)
        _register_users_endpoint()
        _register_empty_activity(42)

        result = runner.invoke(cli, ["contacts", "export", "42"])
        assert result.exit_code == 0, result.output
        assert "bob-jones-42.md" in result.output

    @responses.activate
    def test_export_with_notes(self, runner, mock_token):
        contact = {"id": 1, "name": "Test", "type": "Person"}
        _register_single_contact(1, contact)
        _register_users_endpoint()

        # Notes with a comment
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 50, "created_at": "2026-01-26", "creator": 10, "content": "Called client."},
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        # Comments for the note
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={
                "comments": [
                    {"id": 500, "creator": 10, "created_at": "2026-01-27", "body": "Will follow up."},
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        # Tasks
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Events
        responses.add(
            responses.GET,
            f"{BASE_URL}events",
            json={"events": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Workflows (3 calls)
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE_URL}workflows",
                json={"workflows": [], "meta": {"total_pages": 1}},
                status=200,
            )
        # Opportunities
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities",
            json={"opportunities": [], "meta": {"total_pages": 1}},
            status=200,
        )

        result = runner.invoke(cli, ["contacts", "export", "1", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "### Note" in result.output
        assert "Called client." in result.output
        assert "Will follow up." in result.output

    @responses.activate
    def test_export_includes_all_tasks(self, runner, mock_token):
        """Verify both completed and incomplete tasks are exported."""
        contact = {"id": 1, "name": "Test", "type": "Person"}
        _register_single_contact(1, contact)
        _register_users_endpoint()

        # Notes empty
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={"status_updates": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Tasks — includes completed and incomplete, linked to contact
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={
                "tasks": [
                    {"id": 10, "name": "Open task", "completed": False, "due_date": "2026-02-01", "linked_to": [{"id": 1, "type": "Contact"}]},
                    {"id": 11, "name": "Done task", "completed": True, "due_date": "2026-01-15", "linked_to": [{"id": 1, "type": "Contact"}]},
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        # Comments for each task
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={"comments": [], "meta": {"total_pages": 1}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={"comments": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Events
        responses.add(
            responses.GET,
            f"{BASE_URL}events",
            json={"events": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Workflows (3 calls)
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE_URL}workflows",
                json={"workflows": [], "meta": {"total_pages": 1}},
                status=200,
            )
        # Opportunities
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities",
            json={"opportunities": [], "meta": {"total_pages": 1}},
            status=200,
        )

        result = runner.invoke(cli, ["contacts", "export", "1", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "Open task" in result.output
        assert "Done task" in result.output


# ---------------------------------------------------------------------------
# Integration tests: household resolution
# ---------------------------------------------------------------------------


class TestResolveHousehold:
    @responses.activate
    def test_household_type_contact(self, runner, mock_token):
        """Exporting a Household-type contact fetches all members."""
        household = {
            "id": 200,
            "name": "Smith Household",
            "type": "Household",
            "members": [
                {"contact": {"id": 101, "name": "John Smith"}},
                {"contact": {"id": 102, "name": "Jane Smith"}},
            ],
        }
        _register_single_contact(200, household)
        _register_single_contact(101, {"id": 101, "name": "John Smith", "type": "Person"})
        _register_single_contact(102, {"id": 102, "name": "Jane Smith", "type": "Person"})
        _register_users_endpoint()
        # Empty activity for both members
        _register_empty_activity(101)
        _register_empty_activity(102)

        result = runner.invoke(cli, ["contacts", "export", "200", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "## Household Members" in result.output
        assert "### John Smith" in result.output
        assert "### Jane Smith" in result.output
        assert 'title: "Smith Household"' in result.output

    @responses.activate
    def test_person_in_household(self, runner, mock_token):
        """Exporting a person who belongs to a household includes all members."""
        person = {
            "id": 101,
            "name": "John Smith",
            "type": "Person",
            "household": {"id": 200, "name": "Smith HH"},
        }
        household = {
            "id": 200,
            "name": "Smith Household",
            "type": "Household",
            "members": [
                {"contact": {"id": 101, "name": "John Smith"}},
                {"contact": {"id": 102, "name": "Jane Smith"}},
            ],
        }
        _register_single_contact(101, person)
        _register_single_contact(200, household)
        # Members fetched individually
        _register_single_contact(101, {"id": 101, "name": "John Smith", "type": "Person"})
        _register_single_contact(102, {"id": 102, "name": "Jane Smith", "type": "Person"})
        _register_users_endpoint()
        _register_empty_activity(101)
        _register_empty_activity(102)

        result = runner.invoke(cli, ["contacts", "export", "101", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "## Household Members" in result.output
        assert "### John Smith" in result.output
        assert "### Jane Smith" in result.output

    @responses.activate
    def test_person_no_household(self, runner, mock_token):
        """Exporting a person with no household exports just that person."""
        person = {"id": 300, "name": "Solo Person", "type": "Person"}
        _register_single_contact(300, person)
        _register_users_endpoint()
        _register_empty_activity(300)

        result = runner.invoke(cli, ["contacts", "export", "300", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "# Solo Person" in result.output
        assert "Household Members" not in result.output

    @responses.activate
    def test_household_dedup(self, runner, mock_token):
        """Shared activity across household members is not duplicated."""
        household = {
            "id": 200,
            "name": "HH",
            "type": "Household",
            "members": [
                {"contact": {"id": 101}},
                {"contact": {"id": 102}},
            ],
        }
        _register_single_contact(200, household)
        _register_single_contact(101, {"id": 101, "name": "A", "type": "Person"})
        _register_single_contact(102, {"id": 102, "name": "B", "type": "Person"})
        _register_users_endpoint()

        shared_note = {"id": 999, "created_at": "2026-01-20", "creator": 10, "content": "Shared note"}

        # Member 101 notes
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={"status_updates": [shared_note], "meta": {"total_pages": 1}},
            status=200,
        )
        # Comments for the note from member 101
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={"comments": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Tasks, events, workflows, opps for member 101
        responses.add(responses.GET, f"{BASE_URL}tasks", json={"tasks": [], "meta": {"total_pages": 1}}, status=200)
        responses.add(responses.GET, f"{BASE_URL}events", json={"events": [], "meta": {"total_pages": 1}}, status=200)
        for _ in range(3):
            responses.add(responses.GET, f"{BASE_URL}workflows", json={"workflows": [], "meta": {"total_pages": 1}}, status=200)
        responses.add(responses.GET, f"{BASE_URL}opportunities", json={"opportunities": [], "meta": {"total_pages": 1}}, status=200)

        # Member 102 notes — same shared note
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={"status_updates": [shared_note], "meta": {"total_pages": 1}},
            status=200,
        )
        # Comments for the note from member 102 — should NOT be fetched (deduped)
        # But the note itself is skipped, so no comments call
        # Tasks, events, workflows, opps for member 102
        responses.add(responses.GET, f"{BASE_URL}tasks", json={"tasks": [], "meta": {"total_pages": 1}}, status=200)
        responses.add(responses.GET, f"{BASE_URL}events", json={"events": [], "meta": {"total_pages": 1}}, status=200)
        for _ in range(3):
            responses.add(responses.GET, f"{BASE_URL}workflows", json={"workflows": [], "meta": {"total_pages": 1}}, status=200)
        responses.add(responses.GET, f"{BASE_URL}opportunities", json={"opportunities": [], "meta": {"total_pages": 1}}, status=200)

        result = runner.invoke(cli, ["contacts", "export", "200", "--stdout"])
        assert result.exit_code == 0, result.output
        # The note should appear exactly once
        assert result.output.count("Shared note") == 1


# ---------------------------------------------------------------------------
# Regression tests: Bug 1 — household members key is "members"
# ---------------------------------------------------------------------------


class TestFetchHouseholdMembers:
    @responses.activate
    def test_members_key(self):
        """Bug 1: API uses 'members' key, not 'household_members'."""
        from wealthbox import WealthBox

        client = WealthBox(token="test")

        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/101",
            json={"id": 101, "name": "John", "type": "Person"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/102",
            json={"id": 102, "name": "Jane", "type": "Person"},
            status=200,
        )

        household = {
            "id": 200,
            "name": "Smith HH",
            "type": "Household",
            "members": [
                {"contact": {"id": 101}},
                {"contact": {"id": 102}},
            ],
        }
        members = _fetch_household_members(client, household)
        assert len(members) == 2
        assert members[0]["name"] == "John"
        assert members[1]["name"] == "Jane"

    @responses.activate
    def test_old_key_returns_empty(self):
        """If data only has the old 'household_members' key, returns empty."""
        from wealthbox import WealthBox

        client = WealthBox(token="test")

        household = {
            "id": 200,
            "name": "Smith HH",
            "type": "Household",
            "household_members": [
                {"contact": {"id": 101}},
            ],
        }
        members = _fetch_household_members(client, household)
        assert len(members) == 0


# ---------------------------------------------------------------------------
# Regression tests: Bug 2 — opportunities filtered by linked_to
# ---------------------------------------------------------------------------


class TestOpportunitiesFiltering:
    @responses.activate
    def test_only_linked_opps_exported(self, runner, mock_token):
        """Bug 2: only opps whose linked_to includes a member should appear."""
        contact = {"id": 1, "name": "Test Client", "type": "Person"}
        _register_single_contact(1, contact)
        _register_users_endpoint()

        # Notes, tasks, events, workflows — all empty
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={"status_updates": [], "meta": {"total_pages": 1}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}events",
            json={"events": [], "meta": {"total_pages": 1}},
            status=200,
        )
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE_URL}workflows",
                json={"workflows": [], "meta": {"total_pages": 1}},
                status=200,
            )

        # Opportunities — mix of linked and unlinked
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities",
            json={
                "opportunities": [
                    {
                        "id": 10,
                        "name": "Linked Opp",
                        "linked_to": [{"id": 1, "type": "Contact"}],
                        "target_close": "2026-06-01",
                    },
                    {
                        "id": 11,
                        "name": "Unrelated Opp",
                        "linked_to": [{"id": 999, "type": "Contact"}],
                        "target_close": "2026-07-01",
                    },
                    {
                        "id": 12,
                        "name": "No Links Opp",
                        "target_close": "2026-08-01",
                    },
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )

        result = runner.invoke(cli, ["contacts", "export", "1", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "Linked Opp" in result.output
        assert "Unrelated Opp" not in result.output
        assert "No Links Opp" not in result.output


# ---------------------------------------------------------------------------
# Regression tests: Bug 5 — timeline uses target_close for opportunities
# ---------------------------------------------------------------------------


class TestTimelineTargetClose:
    def test_opportunity_uses_target_close(self):
        """Bug 5: timeline sorts opps by target_close, not close_date."""
        activity = {
            "notes": [],
            "tasks": [],
            "events": [],
            "workflows": [],
            "opportunities": [
                {"id": 1, "name": "Early", "target_close": "2026-01-01"},
                {"id": 2, "name": "Late", "target_close": "2026-12-01"},
            ],
        }
        timeline = _merge_activity_timeline(activity)
        assert len(timeline) == 2
        # Late should come first (reverse chronological)
        assert timeline[0]["name"] == "Late"
        assert timeline[1]["name"] == "Early"

    def test_close_date_ignored(self):
        """Bug 5: close_date field should NOT be used for sorting."""
        activity = {
            "notes": [],
            "tasks": [],
            "events": [],
            "workflows": [],
            "opportunities": [
                {"id": 1, "name": "Has target", "target_close": "2026-06-01"},
                {"id": 2, "name": "Old field only", "close_date": "2026-12-01"},
            ],
        }
        timeline = _merge_activity_timeline(activity)
        # "Has target" sorts to 2026-06-01; "Old field only" has no
        # target_close so falls back to created_at (missing) → datetime.min
        assert timeline[0]["name"] == "Has target"
        assert timeline[1]["name"] == "Old field only"


# ---------------------------------------------------------------------------
# Regression tests: Task API edge cases (from live API debugging)
# ---------------------------------------------------------------------------


class TestTasksFiltering:
    @responses.activate
    def test_only_linked_tasks_exported(self, runner, mock_token):
        """Tasks are filtered by linked_to, same as opportunities."""
        contact = {"id": 1, "name": "Test", "type": "Person"}
        _register_single_contact(1, contact)
        _register_users_endpoint()

        # Notes, events, workflows — empty (per-member loop)
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={"status_updates": [], "meta": {"total_pages": 1}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}events",
            json={"events": [], "meta": {"total_pages": 1}},
            status=200,
        )
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE_URL}workflows",
                json={"workflows": [], "meta": {"total_pages": 1}},
                status=200,
            )

        # Tasks — mix of linked and unlinked (fetched after loop)
        linked_tasks = [
            {
                "id": 10,
                "name": "Linked Task",
                "completed": False,
                "due_date": "2026-02-01",
                "linked_to": [{"id": 1, "type": "Contact"}],
            },
            {
                "id": 11,
                "name": "Unrelated Task",
                "completed": False,
                "due_date": "2026-02-01",
                "linked_to": [{"id": 999, "type": "Contact"}],
            },
            {
                "id": 12,
                "name": "No Link Task",
                "completed": False,
                "due_date": "2026-02-01",
            },
        ]
        # completed=false
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": linked_tasks, "meta": {"total_pages": 1}},
            status=200,
        )
        # completed=true
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Comments for the one linked task
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={"comments": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Opportunities
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities",
            json={"opportunities": [], "meta": {"total_pages": 1}},
            status=200,
        )

        result = runner.invoke(cli, ["contacts", "export", "1", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "Linked Task" in result.output
        assert "Unrelated Task" not in result.output
        assert "No Link Task" not in result.output

    @responses.activate
    def test_completed_and_incomplete_tasks(self, runner, mock_token):
        """Both completed and incomplete tasks appear in export."""
        contact = {"id": 1, "name": "Test", "type": "Person"}
        _register_single_contact(1, contact)
        _register_users_endpoint()

        # Per-member loop: notes, events, workflows — empty
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={"status_updates": [], "meta": {"total_pages": 1}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}events",
            json={"events": [], "meta": {"total_pages": 1}},
            status=200,
        )
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE_URL}workflows",
                json={"workflows": [], "meta": {"total_pages": 1}},
                status=200,
            )

        # Tasks completed=false — one open task
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={
                "tasks": [
                    {
                        "id": 10,
                        "name": "Open task",
                        "complete": False,
                        "due_date": "2026-02-01",
                        "linked_to": [{"id": 1, "type": "Contact"}],
                    },
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        # Tasks completed=true — one done task
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={
                "tasks": [
                    {
                        "id": 11,
                        "name": "Done task",
                        "complete": True,
                        "due_date": "2026-01-15",
                        "linked_to": [{"id": 1, "type": "Contact"}],
                    },
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )
        # Comments for both tasks
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={"comments": [], "meta": {"total_pages": 1}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={"comments": [], "meta": {"total_pages": 1}},
            status=200,
        )
        # Opportunities
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities",
            json={"opportunities": [], "meta": {"total_pages": 1}},
            status=200,
        )

        result = runner.invoke(cli, ["contacts", "export", "1", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "Open task" in result.output
        assert "Done task" in result.output


# ---------------------------------------------------------------------------
# Regression tests: Household ID in linked_to filter
# ---------------------------------------------------------------------------


class TestHouseholdIdInFilter:
    @responses.activate
    def test_opp_linked_to_household_id(self, runner, mock_token):
        """Opps linked to the household contact itself (not just members)."""
        household = {
            "id": 200,
            "name": "Smith HH",
            "type": "Household",
            "members": [
                {"contact": {"id": 101, "name": "John"}},
            ],
        }
        _register_single_contact(200, household)
        _register_single_contact(101, {"id": 101, "name": "John", "type": "Person"})
        _register_users_endpoint()

        # Per-member activity for member 101 — all empty
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={"status_updates": [], "meta": {"total_pages": 1}},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}events",
            json={"events": [], "meta": {"total_pages": 1}},
            status=200,
        )
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{BASE_URL}workflows",
                json={"workflows": [], "meta": {"total_pages": 1}},
                status=200,
            )

        # Tasks — empty
        for _ in range(2):
            responses.add(
                responses.GET,
                f"{BASE_URL}tasks",
                json={"tasks": [], "meta": {"total_pages": 1}},
                status=200,
            )

        # Opportunities — one linked to household ID 200, one to member 101
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities",
            json={
                "opportunities": [
                    {
                        "id": 50,
                        "name": "Household Opp",
                        "linked_to": [{"id": 200, "type": "Contact"}],
                        "target_close": "2026-06-01",
                    },
                    {
                        "id": 51,
                        "name": "Member Opp",
                        "linked_to": [{"id": 101, "type": "Contact"}],
                        "target_close": "2026-07-01",
                    },
                    {
                        "id": 52,
                        "name": "Other Opp",
                        "linked_to": [{"id": 999, "type": "Contact"}],
                        "target_close": "2026-08-01",
                    },
                ],
                "meta": {"total_pages": 1},
            },
            status=200,
        )

        result = runner.invoke(cli, ["contacts", "export", "200", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "Household Opp" in result.output
        assert "Member Opp" in result.output
        assert "Other Opp" not in result.output


# ---------------------------------------------------------------------------
# Regression tests: Members with direct ID format
# ---------------------------------------------------------------------------


class TestMembersDirectIdFormat:
    @responses.activate
    def test_member_with_direct_id(self):
        """Live API returns members as {id: N, type: ...} not {contact: {id: N}}."""
        from wealthbox import WealthBox

        client = WealthBox(token="test")

        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/101",
            json={"id": 101, "name": "John", "type": "Person"},
            status=200,
        )

        # Live API format: direct id at top level
        household = {
            "id": 200,
            "name": "Smith HH",
            "type": "Household",
            "members": [
                {"id": 101, "type": "Person", "first_name": "John", "last_name": "Smith", "title": "Primary"},
            ],
        }
        members = _fetch_household_members(client, household)
        assert len(members) == 1
        assert members[0]["name"] == "John"

    @responses.activate
    def test_member_mixed_formats(self):
        """Handle both nested contact and direct id formats."""
        from wealthbox import WealthBox

        client = WealthBox(token="test")

        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/101",
            json={"id": 101, "name": "John", "type": "Person"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/102",
            json={"id": 102, "name": "Jane", "type": "Person"},
            status=200,
        )

        household = {
            "id": 200,
            "name": "Smith HH",
            "type": "Household",
            "members": [
                {"contact": {"id": 101}},  # nested format
                {"id": 102, "type": "Person", "first_name": "Jane"},  # direct format
            ],
        }
        members = _fetch_household_members(client, household)
        assert len(members) == 2
        assert members[0]["name"] == "John"
        assert members[1]["name"] == "Jane"
