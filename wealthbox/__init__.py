from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from json import JSONDecodeError
from typing import Any, Iterable
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import datetime

import importlib.metadata
try:
    __version__ = importlib.metadata.version("wealthbox")  # your distribution name
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"


class WealthBoxError(Exception):
    """Base exception for WealthBox API errors."""
    pass


class WealthBoxAPIError(WealthBoxError):
    """Error returned by the WealthBox API."""
    def __init__(self, message: str, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response


class WealthBoxResponseError(WealthBoxError):
    """Error parsing response from WealthBox API."""
    def __init__(self, message: str, response_text: str | None = None) -> None:
        super().__init__(message)
        self.response_text = response_text


class WealthBoxRateLimitError(WealthBoxError):
    """Rate limit exceeded."""
    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Filter utilities — work on any list of dicts from the API
# ---------------------------------------------------------------------------


def filter_by_date(
    items: list[dict[str, Any]],
    since_date: str,
    date_fields: tuple[str, ...] = ("created_at", "updated_at"),
) -> list[dict[str, Any]]:
    """Keep items where any date_field >= since_date (ISO string comparison)."""
    return [
        item
        for item in items
        if any(item.get(f, "") >= since_date for f in date_fields)
    ]


def filter_by_tag(
    items: list[dict[str, Any]],
    tag: str,
) -> list[dict[str, Any]]:
    """Keep items that have a tag matching the given name (case-insensitive)."""
    tag_lower = tag.lower()
    return [
        item
        for item in items
        if any(
            t.get("name", "").lower() == tag_lower
            for t in item.get("tags", [])
        )
    ]


def normalize_tags(tags: Iterable[str | dict[str, Any]]) -> list[str]:
    """Normalize tags to the request shape the API accepts on writes.

    WealthBox write bodies want tags as an array of name strings
    (``["a", "b"]``), but read responses return them as objects
    (``[{"id": 1, "name": "a"}]``). Sending the object shape in a write
    body fails with HTTP 400. Accept either shape and emit the request
    shape, so records read from the API can be written back unchanged.
    """
    return [t["name"] if isinstance(t, dict) else t for t in tags]


def sort_and_limit(
    items: list[dict[str, Any]],
    order: str = "desc",
    limit: int | None = None,
    key: str = "created_at",
) -> list[dict[str, Any]]:
    """Sort items by key and optionally cap at limit results."""
    result = sorted(
        items,
        key=lambda item: item.get(key, ""),
        reverse=(order == "desc"),
    )
    if limit is not None:
        return result[:limit]
    return result


class WealthBox:

    def __init__(
        self,
        token: str | None = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        rate_limit_retries: int = 5,
        rate_limit_max_wait: int = 120,
        timeout: float | None = 30,
        page_workers: int = 8,
    ) -> None:
        self.token = token
        self.user_id: int | None = None
        self.base_url = "https://api.crmworkspace.com/v1/"
        self.timeout = timeout
        self._rate_limit_retries = rate_limit_retries
        self._rate_limit_max_wait = rate_limit_max_wait
        # The WB API caps per_page at 100 server-side, so a full pull is
        # total_count/100 pages; pages 2..N are fetched concurrently.
        self._page_workers = max(1, page_workers)
        # custom field definitions per document_type, cached for name→id lookup
        self._custom_field_cache: dict[str, list[dict[str, Any]]] = {}

        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504],
            # POST is excluded: a create that succeeded server-side but came
            # back as a 5xx would be replayed and create a duplicate record.
            allowed_methods=["GET", "PUT", "DELETE"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)

        self._session = requests.Session()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update({'ACCESS_TOKEN': self.token})

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> int | None:
        """Parse the Retry-After header of a 429, tolerating non-integer values."""
        retry_after = response.headers.get('Retry-After')
        try:
            # Retry-After may legally be an HTTP-date; treat that as unknown
            return int(retry_after) if retry_after else None
        except ValueError:
            return None

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Issue a request, sleeping and retrying on 429 rate limits.

        Raises WealthBoxRateLimitError once retries are exhausted or the
        server asks for a wait longer than rate_limit_max_wait.
        """
        kwargs.setdefault('timeout', self.timeout)
        for attempt in range(self._rate_limit_retries + 1):
            res = self._session.request(method, url, **kwargs)
            if res.status_code != 429:
                return res
            wait_time = self._retry_after_seconds(res) or 60  # default 60s
            if attempt < self._rate_limit_retries and wait_time <= self._rate_limit_max_wait:
                time.sleep(wait_time)
            else:
                raise WealthBoxRateLimitError(
                    "Rate limit exceeded",
                    retry_after=self._retry_after_seconds(res)
                )
        return res  # unreachable but satisfies type checker

    def _raise_for_status(
        self,
        res: requests.Response,
        method: str,
        endpoint: str,
    ) -> None:
        """Raise WealthBoxAPIError with status and response body on 4xx/5xx.

        The body is included in the message itself so consumers that only
        see ``str(exc)`` (agents, CLIs, logs) get the API's actual
        validation message, not just the status code.
        """
        if res.status_code < 400:
            return
        body = res.text[:500] if res.text else ""
        try:
            response = res.json()
        except JSONDecodeError:
            response = None
        raise WealthBoxAPIError(
            f"WealthBox {method} /{endpoint} failed ({res.status_code}): {body}",
            response=response,
        )

    def _json_or_raise(
        self,
        res: requests.Response,
        method: str,
        endpoint: str,
    ) -> Any:
        """Raise on HTTP error, then decode and return the JSON body."""
        self._raise_for_status(res, method, endpoint)
        try:
            return res.json()
        except JSONDecodeError as e:
            raise WealthBoxResponseError(
                f"Failed to decode JSON response: {e}",
                response_text=res.text
            )

    @staticmethod
    def _normalize_write_data(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize known asymmetric fields in a write body (currently tags)."""
        if "tags" in data and data["tags"] is not None:
            data = {**data, "tags": normalize_tags(data["tags"])}
        return data

    def raw_request(self, url_completion: str) -> requests.Response:
        return self._request('GET', self.base_url + url_completion)


    @staticmethod
    def _bracketize(params: dict[str, Any]) -> dict[str, Any]:
        """Rewrite list/tuple param keys to ``key[]`` bracket-array form.

        The Wealthbox API takes only the LAST value of repeated query params
        (``?k=a&k=b`` → ``b`` wins), which is what ``requests`` emits for list
        values by default. The bracket form is OR-merged by the API for filters
        documented as ``array[string]`` (e.g. ``tags``). For scalar-string
        filters (``contact_type``, ``type``, ...) the API rejects bracket
        syntax with HTTP 500 — passing a list to a scalar filter is a usage
        error; fan out client-side instead.
        """
        return {
            (f"{k}[]" if isinstance(v, (list, tuple)) and not k.endswith('[]') else k): v
            for k, v in params.items()
        }

    def _fetch_page(
        self,
        url: str,
        params: dict[str, Any],
        page: int,
        endpoint: str,
        key: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch one page, returning (records, total_pages).

        Builds its own param copy with the page number so it is safe to call
        concurrently across threads.
        """
        page_params = {**params, 'page': page}
        res = self._request('GET', url, params=page_params)
        res_json = self._json_or_raise(res, 'GET', endpoint)
        total_pages = res_json['meta']['total_pages']
        if key not in res_json:
            raise WealthBoxAPIError(
                f"Expected key '{key}' not found in response",
                response=res_json
            )
        return res_json[key], total_pages

    def api_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        extract_key: str | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """GET an endpoint, paginating automatically across all pages.

        Pages 2..N are fetched concurrently (``page_workers`` threads) since
        the WB API caps ``per_page`` at 100 server-side and serves concurrent
        page requests cleanly — a large pull is many sequential round-trips
        otherwise. Results are reassembled in page order.

        ``max_results`` stops fetching once that many records are collected
        (only the pages needed are requested), then truncates to the limit.

        See :meth:`_bracketize` for how list-valued filter params are encoded.
        """
        url = self.base_url + endpoint
        params = self._bracketize(params if params else {})
        params.setdefault('per_page', '500')
        key = (extract_key if extract_key is not None else endpoint).split('/')[-1]

        # Page 1 — also tells us total_pages and the server's real page size
        first = {**params, 'page': 1}
        res_json = self._json_or_raise(
            self._request('GET', url, params=first), 'GET', endpoint
        )
        if 'meta' not in res_json:
            # Non-paginated endpoint (e.g. /me) returns the bare object
            return res_json
        if key not in res_json:
            raise WealthBoxAPIError(
                f"Expected key '{key}' not found in response", response=res_json
            )

        total_pages = res_json['meta']['total_pages']
        results: list[dict[str, Any]] = list(res_json[key])

        # Decide how many more pages we actually need
        last_page = total_pages
        if max_results is not None:
            if len(results) >= max_results:
                return results[:max_results]
            page_size = len(results) or 1
            still_needed = max_results - len(results)
            additional_pages = -(-still_needed // page_size)  # ceil division
            last_page = min(total_pages, 1 + additional_pages)

        if last_page <= 1:
            return results[:max_results] if max_results is not None else results

        remaining = list(range(2, last_page + 1))
        by_page: dict[int, list[dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=self._page_workers) as pool:
            futures = {
                pool.submit(self._fetch_page, url, params, p, endpoint, key): p
                for p in remaining
            }
            for fut in futures:
                by_page[futures[fut]] = fut.result()[0]

        for p in remaining:
            results.extend(by_page[p])

        return results[:max_results] if max_results is not None else results

    def count(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> int:
        """Return total record count for a list endpoint without fetching it.

        Issues a single ``per_page=1`` request and reads ``meta.total_count``.
        """
        url = self.base_url + endpoint
        req_params = self._bracketize(params if params else {})
        req_params['per_page'] = '1'
        req_params['page'] = 1
        res_json = self._json_or_raise(
            self._request('GET', url, params=req_params), 'GET', endpoint
        )
        meta = res_json.get('meta', {})
        return meta.get('total_count', 0)

    def api_put(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        data = self._normalize_write_data(data)
        res = self._request('PUT', self.base_url + endpoint, json=data)
        return self._json_or_raise(res, 'PUT', endpoint)

    def api_post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        data = self._normalize_write_data(data)
        res = self._request('POST', self.base_url + endpoint, json=data)
        return self._json_or_raise(res, 'POST', endpoint)

    def api_delete(self, endpoint: str) -> bool:
        """Delete a resource. Returns True if successful (204 status)."""
        res = self._request('DELETE', self.base_url + endpoint)
        if res.status_code in (200, 204):
            return True
        self._raise_for_status(res, 'DELETE', endpoint)
        raise WealthBoxAPIError(
            f"WealthBox DELETE /{endpoint} returned unexpected status {res.status_code}"
        )

    def api_get_single(
        self,
        endpoint: str
    ) -> dict[str, Any]:
        """Get a single resource by ID."""
        res = self._request('GET', self.base_url + endpoint)
        return self._json_or_raise(res, 'GET', endpoint)

    def get_contacts(
        self,
        filters: dict[str, Any] | None = None,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get contacts, optionally filtered. Paginates automatically.

        ``max_results`` caps the number returned and stops paginating early,
        so a small slice of a large workspace doesn't pull every page.

        Filter keys (https://dev.wealthbox.com/#contacts is authoritative;
        the names below may rot):

        Array filters — pass a list to OR-filter:
            tags  — only contacts having ANY of the named tags

        Scalar filters — pass a single value. Passing a list is a usage
        error: the API will return HTTP 500 because the library serializes
        lists as ``key[]=...`` bracket syntax, which the API only accepts
        for documented ``array[string]`` fields:
            id, name, email, phone, contact_type, type, active, deleted,
            household_title, external_unique_id, order,
            updated_since, updated_before, deleted_since

        Example::

            # OR-filter on tags (server-side)
            wb.get_contacts({"type": "Person", "tags": ["VIP", "Top 10"]})

            # contact_type doesn't support OR — fan out client-side
            seen, out = set(), []
            for ct in ("Client", "Trustee"):
                for c in wb.get_contacts({"type": "Person", "contact_type": ct}):
                    if c["id"] not in seen:
                        seen.add(c["id"]); out.append(c)
        """
        return self.api_request('contacts', params=filters, max_results=max_results)

    def get_contact_by_name(self, name: str) -> list[dict[str, Any]]:
        return self.get_contacts({'name': name})

    def get_contact(self, contact_id: int) -> dict[str, Any]:
        """Get a single contact by ID."""
        return self.api_get_single(f'contacts/{contact_id}')

    def create_contact(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new contact.

        Args:
            data: Contact data including fields like first_name, last_name,
                  email_addresses, phone_numbers, etc. ``tags`` must be an
                  array of tag-name strings on write (responses return
                  ``[{id, name}]`` objects; either shape is accepted here
                  and normalized via :func:`normalize_tags`).

        Returns:
            The created contact data.
        """
        return self.api_post('contacts', data)

    def delete_contact(self, contact_id: int) -> bool:
        """Delete a contact by ID.

        Returns:
            True if deletion was successful.
        """
        return self.api_delete(f'contacts/{contact_id}')

    def get_tasks(
        self,
        resource_id: int | None = None,
        resource_type: str | None = None,
        assigned_to: int | None = None,
        completed: bool | str | None = None,
        other_filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get tasks, optionally filtered. Extras via ``other_filters``.

        See https://dev.wealthbox.com/#tasks for filters; ``api_request``
        for list-value semantics.
        """
        default_params: dict[str, Any] = {
            'resource_type': 'contact',
            'completed': 'false',
        }

        called_params: dict[str, Any] = {
            'resource_id': resource_id,
            'resource_type': resource_type,
            'assigned_to': assigned_to,
            'completed': str(completed).lower() if isinstance(completed, bool) else completed
        }
        other_filters = {} if other_filters is None else other_filters
        # Merge dicts and remove keys with None values
        called_params = {k: v for k, v in called_params.items() if v is not None}

        return self.api_request('tasks', params={**default_params, **called_params, **other_filters})

    def get_task(self, task_id: int) -> dict[str, Any]:
        """Get a single task by ID."""
        return self.api_get_single(f'tasks/{task_id}')

    def update_task(self, task_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update a task by ID."""
        return self.api_put(f'tasks/{task_id}', data)

    def delete_task(self, task_id: int) -> bool:
        """Delete a task by ID."""
        return self.api_delete(f'tasks/{task_id}')

    def get_workflows(
        self,
        resource_id: int | None = None,
        resource_type: str | None = None,
        status: str | None = None,
        assigned_to: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get workflows, optionally filtered by assignee.

        Args:
            resource_id: Filter by linked resource ID.
            resource_type: Resource type (default 'contact').
            status: Filter by status: 'active', 'completed', 'scheduled'.
            assigned_to: Client-side filter — keep only workflows with at
                least one step assigned to this user ID. The API does not
                support this natively. When set, workflow_steps are trimmed
                to only the matching steps.
        """
        default_params: dict[str, Any] = {
            'resource_type': 'contact',
            'status': 'active',
        }
        called_params: dict[str, Any] = {
            'resource_id': resource_id,
            'resource_type': resource_type,
            'status': status,
        }
        # Merge dicts and remove keys with None values
        called_params = {k: v for k, v in called_params.items() if v is not None}

        workflows = self.api_request('workflows', params={**default_params, **called_params})

        if assigned_to is None:
            return workflows

        filtered = []
        for wf in workflows:
            steps = wf.get("workflow_steps", [])
            matching = [s for s in steps if s.get("assigned_to") == assigned_to]
            if matching:
                wf_copy = dict(wf)
                wf_copy["workflow_steps"] = matching
                filtered.append(wf_copy)
        return filtered

    def get_workflow(self, workflow_id: int) -> dict[str, Any]:
        """Get a single workflow by ID."""
        return self.api_get_single(f'workflows/{workflow_id}')

    def create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new workflow.

        Args:
            data: Workflow data including template_id, linked_to, etc.
        """
        return self.api_post('workflows', data)

    def delete_workflow(self, workflow_id: int) -> bool:
        """Delete a workflow by ID."""
        return self.api_delete(f'workflows/{workflow_id}')

    def get_workflow_templates(
        self,
        filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get available workflow templates.

        See https://dev.wealthbox.com/#workflow-templates for filters;
        ``api_request`` for list-value semantics.
        """
        return self.api_request('workflow_templates', params=filters)

    def complete_workflow_step(
        self,
        workflow_id: int,
        step_id: int,
        workflow_outcome_id: int | None = None,
    ) -> dict[str, Any]:
        """Mark a workflow step complete.

        ``PUT /workflows/{workflow_id}/steps/{step_id}`` with ``{"complete": true}``
        (verified live). The step is addressed *under its workflow* — there is no
        top-level ``workflow_steps/{id}`` resource. For steps that present outcomes,
        pass ``workflow_outcome_id`` to select which outcome to apply.
        """
        data: dict[str, Any] = {"complete": True}
        if workflow_outcome_id is not None:
            data["workflow_outcome_id"] = workflow_outcome_id
        return self.api_put(f'workflows/{workflow_id}/steps/{step_id}', data)

    def revert_workflow_step(
        self,
        workflow_id: int,
        step_id: int,
    ) -> dict[str, Any]:
        """Revert a completed workflow step.

        ``PUT /workflows/{workflow_id}/steps/{step_id}`` with ``{"revert": true}``
        (verified live).
        """
        return self.api_put(f'workflows/{workflow_id}/steps/{step_id}', {"revert": True})

    def get_events(
        self,
        resource_id: int | None = None,
        resource_type: str = 'contact'
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if resource_id is not None:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        return self.api_request('events', params=params)

    def get_event(self, event_id: int) -> dict[str, Any]:
        """Get a single event by ID."""
        return self.api_get_single(f'events/{event_id}')

    def create_event(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new event.

        Args:
            data: Event data including name, starts_at, ends_at, linked_to, etc.
        """
        return self.api_post('events', data)

    def update_event(self, event_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update an event by ID."""
        return self.api_put(f'events/{event_id}', data)

    def delete_event(self, event_id: int) -> bool:
        """Delete an event by ID."""
        return self.api_delete(f'events/{event_id}')

    def get_opportunities(
        self,
        resource_id: int | None = None,
        resource_type: str | None = None,
        order: str = 'asc',
        include_closed: bool = True
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if resource_id is not None:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        if order:
            params['order'] = order
        if include_closed:
            # Lowercase: requests would serialize a Python bool as "True"
            params['include_closed'] = str(include_closed).lower()
        return self.api_request('opportunities', params=params)

    def get_opportunity(self, opportunity_id: int) -> dict[str, Any]:
        """Get a single opportunity by ID."""
        return self.api_get_single(f'opportunities/{opportunity_id}')

    def create_opportunity(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new opportunity.

        Args:
            data: Opportunity data including name, stage_id, linked_to, etc.
        """
        return self.api_post('opportunities', data)

    def update_opportunity(
        self,
        opportunity_id: int,
        data: dict[str, Any]
    ) -> dict[str, Any]:
        """Update an opportunity by ID."""
        return self.api_put(f'opportunities/{opportunity_id}', data)

    def delete_opportunity(self, opportunity_id: int) -> bool:
        """Delete an opportunity by ID."""
        return self.api_delete(f'opportunities/{opportunity_id}')

    def get_notes(
        self,
        resource_id: int,
        resource_type: str = "contact",
        order: str = "asc",
        since_date: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get notes for a resource, with optional client-side filtering.

        Args:
            resource_id: The resource ID to get notes for.
            resource_type: Resource type (default 'contact').
            order: Sort order, 'asc' or 'desc'.
            since_date: Only return notes created/updated after this ISO
                date string, e.g. '2025-01-15'.
            tag: Only return notes with this tag (case-insensitive).
            limit: Maximum number of notes to return.
        """
        params: dict[str, Any] = {
            'resource_id': resource_id,
            'resource_type': resource_type
        }
        notes = self.api_request('notes', params=params, extract_key='status_updates')

        if since_date is not None:
            notes = filter_by_date(notes, since_date)

        if tag is not None:
            notes = filter_by_tag(notes, tag)

        if order != "asc" or limit is not None:
            notes = sort_and_limit(notes, order=order, limit=limit)

        return notes

    def get_note(self, note_id: int) -> dict[str, Any]:
        """Get a single note by ID."""
        return self.api_get_single(f'notes/{note_id}')

    def create_note(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new note.

        Args:
            data: Note data including content, linked_to, etc. ``tags``
                  must be an array of tag-name strings on write (responses
                  return ``[{id, name}]`` objects; either shape is accepted
                  here and normalized via :func:`normalize_tags`).
        """
        return self.api_post('notes', data)

    def update_note(self, note_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update a note by ID."""
        return self.api_put(f'notes/{note_id}', data)

    def search_notes_by_tag(
        self,
        tag: str,
        order: str = "desc",
        limit: int = 50,
        since_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search all notes across the workspace by tag name.

        Fetches all notes via pagination and filters by tag client-side.
        The WealthBox API does not support server-side tag filtering for notes.

        Args:
            tag: Tag name to filter by (case-insensitive).
            order: Sort order, 'asc' or 'desc' (default 'desc').
            limit: Maximum number of notes to return (default 50).
            since_date: Only return notes created/updated after this ISO
                date string, e.g. '2025-01-15'.
        """
        all_notes = self.api_request(
            "notes", params={}, extract_key="status_updates"
        )

        notes = filter_by_tag(all_notes, tag)

        if since_date is not None:
            notes = filter_by_date(notes, since_date)

        return sort_and_limit(notes, order=order, limit=limit)

    def get_contact_activity(
        self,
        contact_id: int,
        limit: int = 20,
        since_date: str | None = None,
        include_comments: bool = False,
    ) -> list[dict[str, Any]]:
        """Get activity history for a contact (notes, optionally with comments).

        Returns notes sorted most-recent first. By default comments are NOT
        fetched to avoid expensive N+1 API calls — set include_comments=True
        only when you need the full conversation threads.

        Args:
            contact_id: The WealthBox contact ID.
            limit: Maximum number of notes to return (default 20).
            since_date: Only return notes created/updated after this ISO
                date string.
            include_comments: Whether to fetch comments for each note.
        """
        notes = self.get_notes(resource_id=contact_id, since_date=since_date)

        notes = sort_and_limit(notes, order="desc", limit=limit)

        if include_comments:
            for note in notes:
                note["comments"] = self.get_comments(note["id"])

        return notes

    def get_projects(
        self,
        filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all projects.

        See https://dev.wealthbox.com/#projects for filters; ``api_request``
        for list-value semantics.
        """
        return self.api_request('projects', params=filters)

    def get_project(self, project_id: int) -> dict[str, Any]:
        """Get a single project by ID."""
        return self.api_get_single(f'projects/{project_id}')

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new project.

        Args:
            data: Project data including name, linked_to, etc.
        """
        return self.api_post('projects', data)

    def update_project(self, project_id: int, data: dict[str, Any]) -> dict[str, Any]:
        """Update a project by ID."""
        return self.api_put(f'projects/{project_id}', data)

    def delete_project(self, project_id: int) -> bool:
        """Delete a project by ID."""
        return self.api_delete(f'projects/{project_id}')

    def get_categories(self, cat_type: str) -> list[dict[str, Any]]:
        return self.api_request(f'categories/{cat_type}')

    # Convenience wrappers over get_categories for the documented subtypes.
    # These return reference lists of {id, name, ...} used to resolve the
    # integer IDs that other resources reference (e.g. opportunity stage IDs).

    def get_opportunity_stages(self) -> list[dict[str, Any]]:
        """List opportunity stages (id → name reference data)."""
        return self.get_categories('opportunity_stages')

    def get_note_categories(self) -> list[dict[str, Any]]:
        """List note categories."""
        return self.get_categories('note_categories')

    def get_event_categories(self) -> list[dict[str, Any]]:
        """List event categories."""
        return self.get_categories('event_categories')

    def get_project_statuses(self) -> list[dict[str, Any]]:
        """List project statuses."""
        return self.get_categories('project_statuses')

    def get_task_categories(self) -> list[dict[str, Any]]:
        """List task categories."""
        return self.get_categories('task_categories')

    def get_contact_types(self) -> list[dict[str, Any]]:
        """List contact types (Client, Prospect, ...)."""
        return self.get_categories('contact_types')

    def get_tags(self, document_type: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if document_type:
            params['document_type'] = document_type
        return self.api_request('categories/tags', params=params)

    def get_comments(
        self,
        resource_id: int,
        resource_type: str = 'status_update'
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if resource_id:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        return self.api_request('comments', params=params)

    def get_activity(
        self,
        filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get activity feed.

        See https://dev.wealthbox.com/#activity for filters; ``api_request``
        for list-value semantics.
        """
        return self.api_request('activity', params=filters)

    def get_contact_roles(
        self,
        filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get contact roles.

        See https://dev.wealthbox.com/#contact-roles for filters;
        ``api_request`` for list-value semantics.
        """
        return self.api_request('contact_roles', params=filters)

    def get_user_groups(
        self,
        filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get user groups.

        See https://dev.wealthbox.com/#user-groups for filters;
        ``api_request`` for list-value semantics.
        """
        return self.api_request('user_groups', params=filters)

    def add_household_member(
        self,
        household_id: int,
        contact_id: int
    ) -> dict[str, Any]:
        """Add a contact to a household.

        Args:
            household_id: ID of the household contact.
            contact_id: ID of the contact to add as a member.
        """
        return self.api_post(
            'household_members',
            {'household_id': household_id, 'contact_id': contact_id}
        )

    def remove_household_member(
        self,
        household_id: int,
        contact_id: int
    ) -> bool:
        """Remove a contact from a household.

        Args:
            household_id: ID of the household contact.
            contact_id: ID of the contact to remove.
        """
        return self.api_delete(f'household_members/{household_id}/{contact_id}')

    def get_household_members(
        self, household_contact: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Fetch full member contacts from a household contact's member refs.

        Each ``members`` entry is a stub ({id, type, first_name, ...}); this
        fetches the full contact for each via :meth:`get_contact`. Handles both
        ``{"contact": {"id": N}}`` and ``{"id": N}`` member-ref shapes.
        """
        members: list[dict[str, Any]] = []
        for member_ref in household_contact.get("members", []):
            inner = member_ref.get("contact", member_ref)
            member_id = inner.get("id") if isinstance(inner, dict) else None
            if member_id:
                members.append(self.get_contact(member_id))
        return members

    def resolve_household(
        self, contact: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Resolve a contact's household into (members, household_info).

        - If ``contact`` is itself a Household, returns its members.
        - If it belongs to a household, fetches that household's members.
        - Otherwise returns ``([contact], None)``.

        Members fall back to ``[contact]`` if the household lists none.
        ``household_info`` is ``{"id", "name"}`` or ``None``. Related/Linked
        Contacts (parent/child) are NOT available via the API — household
        membership is the only structured relationship data WB exposes.
        """
        if contact.get("type", "") == "Household":
            members = self.get_household_members(contact) or [contact]
            return members, {"id": contact.get("id"), "name": contact.get("name", "")}

        hh_ref = contact.get("household") or {}
        hh_id = hh_ref.get("id")
        if hh_id:
            hh_contact = self.get_contact(hh_id)
            hh_name = hh_contact.get("name", hh_ref.get("name", ""))
            members = self.get_household_members(hh_contact) or [contact]
            return members, {"id": hh_id, "name": hh_name}

        return [contact], None

    def get_my_user_id(self) -> int:
        # This endpoint doesn't have a 'meta'?
        self.user_id = self.api_request('me')['current_user']['id']
        return self.user_id

    def get_my_tasks(self) -> list[dict[str, Any]]:
        if self.user_id is None:
            self.get_my_user_id()
        return self.get_tasks(assigned_to=self.user_id)

    def get_custom_fields(
        self, document_type: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, str] | None = None
        if document_type:
            params = {'document_type': document_type}
        return self.api_request('categories/custom_fields', params=params)

    def _custom_field_defs(self, document_type: str) -> list[dict[str, Any]]:
        """Return (and cache) the custom field definitions for a document type."""
        if document_type not in self._custom_field_cache:
            self._custom_field_cache[document_type] = self.get_custom_fields(document_type)
        return self._custom_field_cache[document_type]

    def build_custom_fields_payload(
        self, document_type: str, values: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Map ``{field_name: value}`` to the API write shape ``[{id, value}]``.

        The API writes custom fields by field **id** (not name), so this looks
        up each name in the definitions for ``document_type`` (e.g. 'Contact',
        'Task') and emits ``{"id": <field_id>, "value": value}``. Raises
        ``ValueError`` on an unknown field name, or — for single_select fields —
        an unknown option (listing valid choices). Per the WB docs the value is
        the option label for selects; the exact wire format for selects was not
        verified against a live write.
        """
        defs = self._custom_field_defs(document_type)
        by_name = {d["name"].lower(): d for d in defs if d.get("name")}
        payload: list[dict[str, Any]] = []
        for name, value in values.items():
            d = by_name.get(name.lower())
            if d is None:
                available = ", ".join(sorted(x["name"] for x in defs if x.get("name")))
                raise ValueError(
                    f"No custom field named {name!r} for {document_type}; "
                    f"available: {available}"
                )
            options = d.get("options") or []
            if d.get("field_type") == "single_select" and options:
                labels = [o.get("label") for o in options if isinstance(o, dict)]
                if value not in labels:
                    raise ValueError(
                        f"{value!r} is not a valid option for {name!r}; "
                        f"choices: {', '.join(l for l in labels if l)}"
                    )
            payload.append({"id": d["id"], "value": value})
        return payload

    @staticmethod
    def get_custom_field_value(record: dict[str, Any], name: str) -> Any:
        """Read a custom field's value from a contact/record by name (case-insensitive).

        Returns ``None`` if the field is absent. Generic form of the Dock-Street
        'Orion Household' lookup (e.g. ``get_custom_field_value(c, 'Orion Household')``).
        """
        for cf in record.get("custom_fields", []) or []:
            if isinstance(cf, dict) and cf.get("name", "").lower() == name.lower():
                return cf.get("value")
        return None

    def update_contact(
        self,
        contact_id: int,
        updates_dict: dict[str, Any],
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a contact. ``custom_fields`` is an optional ``{name: value}``
        dict resolved to the API's ``[{id, value}]`` write shape via
        :meth:`build_custom_fields_payload`."""
        data = dict(updates_dict)
        if custom_fields:
            data["custom_fields"] = self.build_custom_fields_payload(
                "Contact", custom_fields
            )
        return self.api_put(f'contacts/{contact_id}', data)

    def get_notes_with_comments(self, contact_id: int) -> list[dict[str, Any]]:
        notes = self.get_notes(contact_id)
        for note in notes:
            note['comments'] = self.get_comments(note['id'])
        return notes

    def get_events_with_comments(self, contact_id: int) -> list[dict[str, Any]]:
        events = self.get_events(contact_id)
        for event in events:
            event['comments'] = self.get_comments(event['id'], resource_type='event')
        return events

    def get_tasks_with_comments(self, contact_id: int) -> list[dict[str, Any]]:
        tasks = self.get_tasks(contact_id)
        for task in tasks:
            task['comments'] = self.get_comments(task['id'], resource_type='task')
        return tasks

    def get_workflows_with_comments(self, contact_id: int) -> list[dict[str, Any]]:
        # First get all workflows, completed, active and scheduled
        workflows = (
            self.get_workflows(contact_id, status='active') +
            self.get_workflows(contact_id, status='completed') +
            self.get_workflows(contact_id, status='scheduled'))

        for wf in workflows:
            for step in wf['workflow_steps']:
                step['comments'] = self.get_comments(step['id'], resource_type='WorkflowStep')
        return workflows

    def get_users(self) -> list[dict[str, Any]]:
        return self.api_request('users')

    def get_teams(self) -> list[dict[str, Any]]:
        return self.api_request('teams')

    def make_user_map(self, method: str = "full") -> dict[int, str]:
        user_list = self.get_users()
        if method == "full":
            user_dict = {user['id']: f'{user["id"]}; {user["name"]}; {user["email"]}' for user in user_list}
        elif method == "name":
            user_dict = {user['id']: user['name'] for user in user_list}
        elif method == "first_name":
            user_dict = {user['id']: user['name'].split(' ')[0] for user in user_list}
        elif method == "email":
            user_dict = {user['id']: user['email'] for user in user_list}
        else:
            raise ValueError("method must be one of 'full', 'name', 'first_name', or 'email'")

        return user_dict

    def enhance_user_info(
        self,
        wb_data: Any,
        method: str | dict[int, str] = "full"
    ) -> Any:
        """Walk through a structure of data from the API (list of dicts, dict of dicts, etc)
        and replace the 'creator' field with information about the creator"""
        if isinstance(method, dict):
            user_map = method
        else:
            user_map = self.make_user_map(method)

        # if wb_data is not a dict or list, just return it
        if not isinstance(wb_data, (dict, list)):
            return wb_data
        if isinstance(wb_data, dict):
            # Build a new dict — the input is never mutated
            result = {k: self.enhance_user_info(v, user_map) for k, v in wb_data.items()}
            for field in ('creator', 'assigned_to'):
                if field in wb_data:
                    result[field] = user_map.get(wb_data[field], wb_data[field])
            return result
        if isinstance(wb_data, list):
            return [self.enhance_user_info(d, user_map) for d in wb_data]

    def create_task_detailed(
        self,
        name: str,
        due_date: datetime.date | None = None,
        description: str | None = None,
        linked_to: list[dict[str, Any]] | None = None,
        assigned_to: int | None = None,
        assigned_to_team: int | None = None,
        category: int | None = None,
        custom_fields: dict[str, Any] | list[Any] | None = None
    ) -> dict[str, Any]:
        """custom_fields is a dict for setting any custom fields
           dict([Name of Field] : [Value])
        """
        if custom_fields is None:
            custom_fields = []
        if linked_to is None:
            linked_to = []
        if due_date is None:
            due_date = datetime.date.today()
        # due date should be in JSON datetime format
        due_date_str = due_date.strftime('%Y-%m-%dT%H:%M:%SZ')

        if assigned_to is None and assigned_to_team is None:
            assigned_to = self.get_my_user_id()

        data: dict[str, Any] = {
            'name': name,
            'due_date': due_date_str,
            'linked_to': linked_to,
            'resource_type': 'contact',
            'description': description,
            'assigned_to': assigned_to,
            'assigned_to_team': assigned_to_team,
            'custom_fields': custom_fields,
            'category': category,
        }
        return self.api_post('tasks', data)

    def create_task(
        self,
        title: str,
        due_date: datetime.date | None = None,
        description: str | None = None,
        linked_to: int | list[int] | dict[str, Any] | list[dict[str, Any]] | None = None,
        assigned_to: str | None = None,
        category: str | int | None = None,
        **kwargs: Any
    ) -> dict[str, Any]:
        """
        A more user friendly version to create a task
        kwargs can be used to capture any custom fields
        due: string or datetime. If string, should be WB later type "2 days later"
        linked_to: array of ids or a array of dicts
        assigned_to: string name of user or team
        """
        # Get all users and teams
        user_team_map: dict[str, int] = {}
        for user in self.get_users():
            # Insert full name and also first name and last
            user_team_map[user['name']] = user['id']
            user_team_map[user['name'].split(' ')[0]] = user['id']
            user_team_map[user['name'].split(' ')[-1]] = user['id']
        teams = self.get_teams()
        team_names = {team['name'] for team in teams}
        for team in teams:
            user_team_map[team['name']] = team['id']

        assigned_to_id = user_team_map.get(assigned_to) if assigned_to else None
        if assigned_to and assigned_to_id is None:
            # Without this, an unknown name would silently assign the task
            # to the API token's owner (create_task_detailed's fallback)
            raise ValueError(f"No user or team named {assigned_to!r} found")
        is_team = assigned_to in team_names if assigned_to else False

        category_id: int | None
        if isinstance(category, str):
            task_categories = self.get_categories('task_categories')
            matches = [c['id'] for c in task_categories if c['name'] == category]
            if not matches:
                available = ", ".join(sorted(c['name'] for c in task_categories))
                raise ValueError(
                    f"No task category named {category!r}; available: {available}"
                )
            category_id = matches[0]
        else:
            category_id = category

        # for dicts in linked_to, pull out only the id and type fields
        # attempting to handle:
        #  - a single id
        #  - a list of ids
        #  - a dict with id and other keys
        #  - a list of dicts with id and other keys
        linked_to_list: list[dict[str, Any]] | None = None
        if linked_to is not None:
            if not isinstance(linked_to, list):
                linked_to = [linked_to]
            if len(linked_to) > 0:
                if isinstance(linked_to[0], dict):
                    linked_to_list = [{'id': d['id'], 'type': 'Contact'} for d in linked_to]
                else:
                    linked_to_list = [{'id': contact_id, 'type': 'Contact'} for contact_id in linked_to]

        # Get the available custom fields for tasks
        custom_fields = self.get_custom_fields('Task')
        
        cf: dict[str, Any] = {}
        for k, v in kwargs.items():
            # try to match kwargs to custom fields
            # no vetting of values is done
            # replace _ in k with space
            name = k.replace('_', ' ')
            if name in [f['name'] for f in custom_fields]:
                cf[name] = v

        if is_team:
            return self.create_task_detailed(
                title, due_date, description=description,
                linked_to=linked_to_list, assigned_to_team=assigned_to_id,
                category=category_id, custom_fields=cf
            )
        else:
            return self.create_task_detailed(
                title, due_date, description=description,
                linked_to=linked_to_list, assigned_to=assigned_to_id,
                category=category_id, custom_fields=cf
            )