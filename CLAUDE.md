# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python wrapper library for the Wealthbox CRM API (https://api.crmworkspace.com/v1/). Provides a `WealthBox` class that handles authentication, pagination, and common CRM operations.

**Current version:** 0.16.0
**Next milestone:** 1.0 (see ROADMAP.md)

## Development Commands

```bash
# Install dependencies (using venv since poetry may not be available)
python3 -m venv .venv
source .venv/bin/activate
pip install responses pytest requests

# Run tests
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_wealthbox.py::TestApiRequest::test_single_page_response
```

## Publishing

Publishing to PyPI is automated via GitHub Actions. To publish:
1. Update version in `pyproject.toml`
2. Run `poetry lock` to update lock file
3. Commit changes
4. Create a git tag matching `v*.*.*` (e.g., `v0.13.0`)
5. Push the tag to trigger the workflow

## Architecture

The core library is a single module (`wealthbox/__init__.py`) with one main class and custom exceptions. A Click-based CLI lives in `wealthbox/cli/` (optional `click` dependency), with tests in `tests/test_cli/`.

All request paths raise `WealthBoxAPIError` on 4xx/5xx with the status code, method, endpoint, and response body (truncated to 500 chars) in the exception message — the body is where the API names the offending field, so never swallow it.

### Exception Classes
- `WealthBoxError` - Base exception
- `WealthBoxAPIError` - API returned unexpected response (includes `response` dict)
- `WealthBoxResponseError` - Failed to parse response (includes `response_text`)
- `WealthBoxRateLimitError` - 429 response (includes `retry_after` seconds)

### WealthBox Class

Constructor accepts `token`, `max_retries` (default 3), `backoff_factor` (default 0.5), `timeout` (default 30s, passed to every request). Uses `requests.Session` with automatic retry on 500/502/503/504 errors for GET/PUT/DELETE — POST is deliberately not retried so a create that succeeded server-side can't be replayed into a duplicate. All requests funnel through `_request()`, which also sleeps/retries on 429 rate limits.

**Core Methods:**
- `api_request()` - GET with automatic pagination. Pages 2..N are fetched **concurrently** (`page_workers`, default 8) since the API caps `per_page` at 100 server-side — ~6x faster on large pulls. Accepts `max_results` to stop paginating early (only the needed pages are fetched).
- `count()` - total record count from one `per_page=1` request (reads `meta.total_count`) without fetching the list.
- `api_get_single()` - GET single resource by ID
- `api_put()` / `api_post()` / `api_delete()` - Write operations

**Resource Endpoints (full CRUD):**
- Contacts: `get_contacts`, `get_contact`, `create_contact`, `update_contact`, `delete_contact`
- Tasks: `get_tasks`, `get_task`, `create_task`, `update_task`, `delete_task`
- Workflows: `get_workflows`, `get_workflow`, `create_workflow`, `delete_workflow`
- Events: `get_events`, `get_event`, `create_event`, `update_event`, `delete_event`
- Opportunities: `get_opportunities`, `get_opportunity`, `create_opportunity`, `update_opportunity`, `delete_opportunity`
- Notes: `get_notes`, `get_note`, `create_note`, `update_note`
- Projects: `get_projects`, `get_project`, `create_project`, `update_project`, `delete_project`

**Additional Endpoints:**
- `get_workflow_templates()`, `update_workflow_step()`
- `get_activity()`, `get_contact_roles()`, `get_user_groups()`
- `add_household_member()`, `remove_household_member()`, `resolve_household()`, `get_household_members()`
- `get_users()`, `get_teams()`, `get_categories()`, `get_tags()`, `get_custom_fields()`
- Category convenience wrappers: `get_opportunity_stages()`, `get_note_categories()`, `get_event_categories()`, `get_project_statuses()`, `get_task_categories()`, `get_contact_types()`
- `get_comments()`

**Custom fields (write-by-name):**
- `build_custom_fields_payload(document_type, {name: value})` resolves field names to the API's `[{id, value}]` write shape (the API writes custom fields by **id**, not name). `update_contact(id, updates, custom_fields={name: value})` uses it. `get_custom_field_value(record, name)` reads a value by name (case-insensitive).

**Known API holes (cannot be filled — UI-only or undocumented):** Related/Linked Contacts (parent/child) are not in the API; household membership is the only structured relationship data. There is no documented `DELETE /notes/{id}`, `POST /comments`, or `PUT /workflows/{id}` — notes can't be deleted, comments can't be created, and workflows can't be updated (only their steps) via the API.

**Helper Methods:**
- `*_with_comments()` - Fetch resources and attach their comments
- `create_task()` / `create_task_detailed()` - Task creation with user/team lookup
- `enhance_user_info()` - Recursively replaces user IDs with readable info
- `make_user_map()` - Create ID-to-name mapping for users

## Testing

~130 tests in `tests/test_wealthbox.py` (library) plus ~220 in `tests/test_cli/` (CLI commands), using the `responses` library for HTTP mocking. Tests cover all endpoints and error handling paths.

## API Notes

API responses use the endpoint name as the key for result arrays (e.g., `/contacts` returns `{"contacts": [...], "meta": {...}}`). Exception: `/notes` returns `{"status_updates": [...]}`.

**Tag shape asymmetry:** write bodies want `tags` as an array of name strings (`["Clients"]`); read responses return objects (`[{"id": 1, "name": "Clients"}]`). Sending the object shape on a write fails with HTTP 400. `api_post`/`api_put` normalize `tags` via `normalize_tags()` automatically, so records read from the API can be written back as-is.

**Contacts tag filter:** the read filter key is `tags` (list, serialized as `tags[]=`). A bare `tag=` param is silently ignored by the API and returns the full unfiltered contact list (verified live).
