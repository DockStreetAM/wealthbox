# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python wrapper library for the Wealthbox CRM API (https://api.crmworkspace.com/v1/). Provides a `WealthBox` class that handles authentication, pagination, and common CRM operations.

**Current version:** 0.8.0
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
4. Create a git tag matching `v*.*.*` (e.g., `v0.8.0`)
5. Push the tag to trigger the workflow

## Architecture

The library is a single module (`wealthbox/__init__.py`) with one main class and custom exceptions.

### Exception Classes
- `WealthBoxError` - Base exception
- `WealthBoxAPIError` - API returned unexpected response (includes `response` dict)
- `WealthBoxResponseError` - Failed to parse response (includes `response_text`)
- `WealthBoxRateLimitError` - 429 response (includes `retry_after` seconds)

### WealthBox Class

Constructor accepts `token`, `max_retries` (default 3), `backoff_factor` (default 0.5). Uses `requests.Session` with automatic retry on 500/502/503/504 errors.

**Core Methods:**
- `api_request()` - GET with automatic pagination (handles `meta.total_pages`)
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
- `add_household_member()`, `remove_household_member()`
- `get_users()`, `get_teams()`, `get_categories()`, `get_tags()`, `get_custom_fields()`
- `get_comments()`

**Helper Methods:**
- `*_with_comments()` - Fetch resources and attach their comments
- `create_task()` / `create_task_detailed()` - Task creation with user/team lookup
- `enhance_user_info()` - Recursively replaces user IDs with readable info
- `make_user_map()` - Create ID-to-name mapping for users

## Testing

73 tests in `tests/test_wealthbox.py` using `responses` library for HTTP mocking. Tests cover all endpoints and error handling paths.

## API Notes

API responses use the endpoint name as the key for result arrays (e.g., `/contacts` returns `{"contacts": [...], "meta": {...}}`). Exception: `/notes` returns `{"status_updates": [...]}`.
