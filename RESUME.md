# Project State

*Last updated: 2026-05-23*

## What this project is
Python wrapper library for the Wealthbox CRM API (`wealthbox` on PyPI). Single-module design with a `WealthBox` class handling auth, pagination, and CRUD for contacts, tasks, workflows, events, opportunities, notes, and projects. Published via GitHub Actions on tag push.

## Current goal
Library is at **v0.13.0**, just released. This session fixed a silent-wrong-results bug where list-valued filters (e.g. `wb.get_contacts({"tags": ["VIP", "10M"]})`) returned only contacts matching the last value — because Python `requests` serializes lists as repeated query params (`?tags=a&tags=b`) and the Wealthbox API treats repeated params as last-wins, even for filters documented as `array[string]`. Fix rewrites list/tuple values to bracket-array syntax (`tags[]=a&tags[]=b`) in `api_request` before passing to `requests`, which the API correctly OR-merges. Empirically verified live (tags=["10M","11/20"] → 39 = 38+1).

## Key decisions / constraints
- All filtering (date, tag, sort) is client-side because the Wealthbox API doesn't support server-side filtering for these fields
- `search_notes_by_tag` fetches ALL notes workspace-wide — documented trade-off, no API alternative
- `include_comments` on `get_contact_activity` is opt-in to avoid N+1 API calls
- Notes endpoint returns `status_updates` key (not `notes`) — handled via `extract_key` param
- **List-filter encoding (v0.13.0)**: `api_request` auto-rewrites list/tuple values to `key[]=...` because WB last-wins on repeated params. Scalar fields like `contact_type` return HTTP 500 on bracket syntax — callers must fan out client-side (pattern documented in `get_contacts` docstring + README). Knowledge captured in skill `wealthbox-list-filter-bracket-syntax`.

## What works
- 329 tests passing (3 new for bracket-syntax serialization including a parametrized double-bracket guard)
- **v0.13.0** tagged, pushed, and confirmed published to PyPI (workflow run 25989539035 succeeded)
- Filter utilities reused across `get_notes`, `search_notes_by_tag`, `get_contact_activity`
- CLI export functionality (`wb contacts export-all`) with incremental export and workspace deep links
- README.rst now has a proper Filtering section with the array-vs-scalar pattern

## What's broken / missing
- GitHub Dependabot flagged **26 vulnerabilities (11 high, 13 moderate, 2 low)** on the default branch as of the last push — count grew from 18 since prior session
- `CLAUDE.md` still says version 0.8.0 (now even more outdated; actual is 0.13.0)
- Untracked files in repo: `EXPORT_ENHANCEMENT_SPEC.md`, `PRD-wb-cli.md`, `RESUME.md`, `advisor-mcp/`, `exports/` — unclear if these should be committed or gitignored
- GH Actions workflow uses `actions/checkout@v4` (Node.js 20, deprecated June 2026) — non-blocking but flagged in last run

## Next concrete steps
1. Triage 26 Dependabot vulnerabilities — group by direct vs transitive, prioritize high severity (https://github.com/DockStreetAM/wealthbox/security/dependabot)
2. Update `CLAUDE.md` version reference from 0.8.0 to 0.13.0
3. Decide whether `EXPORT_ENHANCEMENT_SPEC.md`, `PRD-wb-cli.md`, `advisor-mcp/`, and `exports/` should be gitignored or committed
4. Bump `actions/checkout@v4` → `@v5` in `.github/workflows/main.yml` before Sept 2026 Node 20 removal
5. Continue toward 1.0 milestone (see ROADMAP.md)

## Open questions
- Are the Dependabot vulnerabilities in direct or transitive dependencies?
- Is the `advisor-mcp/` directory a separate project that should have its own repo?
- For scalar-field OR-filtering (contact_type, type, etc.), is a `fan_out=` helper on `api_request` worth adding, or is "callers fan out themselves" the right ergonomic? (v0.13.0 chose the latter; README documents the pattern.)
