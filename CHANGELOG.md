# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.18.0] - 2026-10-28

### Security
- API token can no longer leak via redirects: redirects are not followed and a 3xx raises.
- IDs in URL paths are validated (`"5/../tasks/9"` or `"5?x=1"` now raise `ValueError`).
- 5xx retries ignore server `Retry-After` (a 503 could previously stall for hours).
- CLI: Rich markup/terminal escape injection from API data fixed; CSV cells starting with
  `= + - @` are quoted against formula injection; exported PII files are written 0600 (dir 0700);
  a `.env` in the current directory is no longer loaded (use `--env-file` or `~/.config/wealthbox/.env`);
  `auth set-token` prompts with hidden input and is blocked under `--readonly`.
- Publish workflow: actions pinned to commit SHAs, read-only permissions, tests and a
  tag/version check run before publishing.

### Fixed
- `tags="VIP"` (bare string) wrote one tag per letter.
- `create_task` sent custom fields by name instead of `[{id, value}]`; ambiguous assignee names now
  raise instead of picking one silently; `linked_to` dicts keep their `type`.
- `export-all --incremental` no longer advances its timestamp when contacts fail, stamps the run
  start (not end), detects new notes/events, removes stale files, honours `--dry-run`, and exits 1 on errors.
- `--set FIELD` without `=` is rejected instead of blanking the field.
- `--limit` stops paginating early for tasks/events/opportunities/projects/workflows.
- CLI exit codes now distinguish not-found, validation, auth and network errors.
- Pagination: missing `total_pages` raises a clear error, remaining pages are cancelled on failure,
  results are de-duplicated by id; `count()` raises when `total_count` is missing; `get_comments(None)`
  raises instead of fetching every comment; null dates no longer crash sorting/filtering;
  network errors raise `WealthBoxConnectionError`; custom-field cache refetches on an unknown name
  (`clear_custom_field_cache()` added); malformed `Retry-After` handled.

## [0.17.2] - 2026-10-27

### Security
- Bumped locked `certifi` to 2026.10.23 (runtime, via `requests`) to clear a
  Dependabot alert (fixed in 2026.10.18).

## [0.17.1] - 2026-10-27

### Security
- Bumped locked `urllib3` 2.7.0 → 2.8.0 (runtime, via `requests`) and `GitPython`
  3.1.50 → 3.2.1 (dev-only, via `python-semantic-release`) to clear Dependabot alerts.

## [0.17.0] - 2026-06-25

### Fixed
- **Workflow steps could never be completed or reverted via the API.**
  `update_workflow_step` targeted `PUT /workflow_steps/{id}`, which WealthBox does
  not expose — every call returned 404 (issue #1). A workflow step is addressed
  **under its workflow**: completion and reversion now use
  `PUT /workflows/{workflow_id}/steps/{step_id}` with a `{"complete": true}` or
  `{"revert": true}` body (both verified against the live API).

### Added
- `complete_workflow_step(workflow_id, step_id, workflow_outcome_id=None)` and
  `revert_workflow_step(workflow_id, step_id)`. Pass `workflow_outcome_id` for steps
  that present outcomes.

### Changed
- `wb workflows complete-step` / `revert-step` now take both `WORKFLOW_ID` and
  `STEP_ID` arguments (`complete-step` also accepts `--outcome-id`).

### Removed
- `update_workflow_step(step_id, data)`. It was non-functional (always 404'd) and its
  signature lacked the `workflow_id` the real endpoint requires, so no working caller
  relied on it. Use `complete_workflow_step` / `revert_workflow_step`.
