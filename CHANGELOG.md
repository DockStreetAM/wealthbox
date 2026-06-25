# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
