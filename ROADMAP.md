# Wealthbox Python Module Roadmap

## Current State (v0.8.0)

- Full CRUD operations for: Contacts, Tasks, Workflows, Events, Opportunities, Notes, Projects
- Additional endpoints: Activity feed, Contact Roles, User Groups, Household Members, Workflow Templates, Workflow Steps
- 73 tests passing
- Exception-based error handling (WealthBoxError, WealthBoxAPIError, WealthBoxResponseError, WealthBoxRateLimitError)
- Session reuse with retry strategy (500/502/503/504)
- Type hints throughout
- Rate limit handling (429)

## Roadmap to v1.0

### 1. Refine Module
- [ ] Clean up deprecated `tool.poetry.dev-dependencies` section in pyproject.toml
- [ ] Review/consolidate helper methods (create_task vs create_task_detailed)
- [ ] Consistent parameter naming across methods
- [ ] Add `__all__` exports

### 2. Complete Endpoint Coverage
- [ ] Review Wealthbox API docs for any missed endpoints
- [ ] Add missing CRUD operations if any
- [ ] Consider adding batch/bulk operations if API supports

### 3. Complete Test Coverage
- [ ] Add edge case tests (empty responses, malformed data)
- [ ] Test error paths more thoroughly
- [ ] Add integration-style tests for composite methods (get_notes_with_comments, etc.)
- [ ] Consider adding pytest coverage reporting

### 4. 1.0 Polish
- [ ] Add comprehensive docstrings
- [ ] Create README with usage examples
- [ ] Add CHANGELOG.md
- [ ] Review public API surface for stability
- [ ] Consider adding async support or leaving for 2.0
