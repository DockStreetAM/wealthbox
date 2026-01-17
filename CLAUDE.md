# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python wrapper library for the Wealthbox CRM API (https://api.crmworkspace.com/v1/). Provides a `WealthBox` class that handles authentication, pagination, and common CRM operations.

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
2. Create a git tag matching `v*.*.*` (e.g., `v0.6.7`)
3. Push the tag to trigger the workflow

## Architecture

The library is a single module (`wealthbox/__init__.py`) with one main class and custom exceptions:

**Exception Classes:**
- `WealthBoxError` - Base exception
- `WealthBoxAPIError` - API returned unexpected response (includes `response` dict)
- `WealthBoxResponseError` - Failed to parse response (includes `response_text`)
- `WealthBoxRateLimitError` - 429 response (includes `retry_after` seconds)

**WealthBox** - API client initialized with an access token
- Constructor accepts `token`, `max_retries` (default 3), `backoff_factor` (default 0.5)
- Uses `requests.Session` with automatic retry on 500/502/503/504 errors
- `api_request()` - Core GET method with automatic pagination (handles `meta.total_pages`)
- `api_put()` / `api_post()` - Write operations
- Resource methods: `get_contacts()`, `get_tasks()`, `get_workflows()`, `get_events()`, `get_opportunities()`, `get_notes()`, `get_users()`, `get_teams()`
- `*_with_comments()` methods fetch resources and attach their comments
- `create_task()` / `create_task_detailed()` - Task creation with user/team lookup
- `enhance_user_info()` - Recursively replaces user IDs with readable info in API responses

API responses use the endpoint name as the key for result arrays (e.g., `/contacts` returns `{"contacts": [...], "meta": {...}}`).
