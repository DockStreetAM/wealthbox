"""Regression tests for the core security/robustness review fixes (H1, M1-M6, L1-L7)."""
import datetime
import json

import pytest
import requests
import responses
import urllib3

import wealthbox
from wealthbox import (
    WealthBox, WealthBoxAPIError, WealthBoxConnectionError, WealthBoxError,
    WealthBoxRateLimitError, WealthBoxResponseError,
    filter_by_date, normalize_tags, sort_and_limit,
)

BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def wb():
    return WealthBox(token="test_token", rate_limit_retries=0)


def _list(key, items, total_pages=1):
    return {key: items, "meta": {"total_pages": total_pages}}


# --- H1 ----------------------------------------------------------------------

class TestNormalizeTagsShapes:
    def test_bare_string_is_one_tag(self):
        assert normalize_tags("VIP") == ["VIP"]

    def test_single_dict_is_one_tag(self):
        assert normalize_tags({"id": 1, "name": "VIP"}) == ["VIP"]

    def test_none_passes_through(self):
        assert normalize_tags(None) is None

    def test_dict_without_name_raises(self):
        with pytest.raises(ValueError, match="no 'name'"):
            normalize_tags([{"id": 1}])

    @responses.activate
    def test_create_contact_bare_string_tag_on_wire(self, wb):
        responses.add(responses.POST, f"{BASE_URL}contacts", json={"id": 1}, status=201)
        wb.create_contact({"first_name": "A", "tags": "VIP"})
        assert json.loads(responses.calls[0].request.body)["tags"] == ["VIP"]


# --- M1 ----------------------------------------------------------------------

class TestRedirectsNotFollowed:
    @responses.activate
    def test_cross_host_redirect_raises_and_token_not_sent(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}contacts/5", status=302,
            headers={"Location": "http://evil.example/y"},
        )
        responses.add(responses.GET, "http://evil.example/y", json={}, status=200)

        with pytest.raises(WealthBoxAPIError, match="redirect"):
            wb.get_contact(5)

        assert len(responses.calls) == 1
        assert all("evil.example" not in c.request.url for c in responses.calls)

    @responses.activate
    def test_raw_request_redirect_raises(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}x", status=301,
            headers={"Location": "https://other.example/x"},
        )
        with pytest.raises(WealthBoxAPIError):
            wb.raw_request("x")
        assert len(responses.calls) == 1

    def test_no_plain_http_adapter_with_retries(self, wb):
        # Only https:// carries the retrying adapter
        assert wb._session.get_adapter("http://x").max_retries.total == 0


# --- M2 ----------------------------------------------------------------------

class TestRetryAfterOn5xxIgnored:
    def test_retry_config_ignores_retry_after(self, wb):
        retry = wb._session.get_adapter(BASE_URL).max_retries
        assert retry.respect_retry_after_header is False

    def test_503_retry_after_does_not_stall(self, wb, monkeypatch):
        slept = []
        monkeypatch.setattr("urllib3.util.retry.time.sleep", slept.append)
        retry = wb._session.get_adapter(BASE_URL).max_retries
        resp = urllib3.HTTPResponse(
            body=b"", status=503, headers={"Retry-After": "21600"},
            preload_content=False,
        )
        retry = retry.increment(method="GET", url="/v1/contacts", response=resp)
        retry = retry.increment(method="GET", url="/v1/contacts", response=resp)
        retry.sleep(resp)
        assert all(s < 60 for s in slept)


# --- M3 ----------------------------------------------------------------------

class TestIdValidation:
    @pytest.mark.parametrize("bad", [
        "5/../../tasks/9", "5?x=1", "abc", "", "-5", "0", 0, -1, True, False,
        None, 1.5, "²",
    ])
    def test_rejects_bad_ids(self, bad):
        with pytest.raises(ValueError):
            WealthBox._id(bad)

    @pytest.mark.parametrize("good,expected", [(5, "5"), ("42", "42")])
    def test_accepts_ints_and_digit_strings(self, good, expected):
        assert WealthBox._id(good) == expected

    @pytest.mark.parametrize("call", [
        lambda wb: wb.get_contact("5/../../tasks/9"),
        lambda wb: wb.delete_contact("5?x=1"),
        lambda wb: wb.update_contact("1/x", {"a": 1}),
        lambda wb: wb.get_task("x"),
        lambda wb: wb.update_task("x", {}),
        lambda wb: wb.delete_task("x"),
        lambda wb: wb.get_workflow("x"),
        lambda wb: wb.delete_workflow("x"),
        lambda wb: wb.complete_workflow_step(1, "2/../3"),
        lambda wb: wb.revert_workflow_step("1/..", 2),
        lambda wb: wb.get_event("x"),
        lambda wb: wb.update_event("x", {}),
        lambda wb: wb.delete_event("x"),
        lambda wb: wb.get_opportunity("x"),
        lambda wb: wb.update_opportunity("x", {}),
        lambda wb: wb.delete_opportunity("x"),
        lambda wb: wb.get_note("x"),
        lambda wb: wb.update_note("x", {}),
        lambda wb: wb.get_project("x"),
        lambda wb: wb.update_project("x", {}),
        lambda wb: wb.delete_project("x"),
        lambda wb: wb.remove_household_member("1/..", 2),
        lambda wb: wb.remove_household_member(1, "2?x"),
    ])
    @responses.activate
    def test_methods_reject_before_any_request(self, wb, call):
        with pytest.raises(ValueError):
            call(wb)
        assert len(responses.calls) == 0

    @responses.activate
    def test_digit_string_id_works(self, wb):
        responses.add(responses.GET, f"{BASE_URL}contacts/7", json={"id": 7}, status=200)
        assert wb.get_contact("7") == {"id": 7}

    @responses.activate
    def test_categories_type_is_quoted(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}categories/..%2Fcontacts",
            json=_list("..%2Fcontacts", []), status=200,
        )
        wb.get_categories("../contacts")
        assert responses.calls[0].request.url.startswith(f"{BASE_URL}categories/..%2Fcontacts")


# --- M5 ----------------------------------------------------------------------

def _task_mocks(users=None, teams=None, custom_fields=None):
    responses.add(responses.GET, f"{BASE_URL}users",
                  json=_list("users", users or [{"id": 1, "name": "User"}]), status=200)
    responses.add(responses.GET, f"{BASE_URL}teams",
                  json=_list("teams", teams or []), status=200)
    responses.add(responses.GET, f"{BASE_URL}categories/custom_fields",
                  json=_list("custom_fields", custom_fields or []), status=200)
    responses.add(responses.POST, f"{BASE_URL}tasks", json={"id": 1}, status=201)


class TestCreateTaskCustomFields:
    @responses.activate
    def test_unknown_custom_field_kwarg_raises(self, wb):
        _task_mocks(custom_fields=[{"id": 77, "name": "Priority Level"}])
        with pytest.raises(ValueError, match="No custom field named 'priorty level'"):
            wb.create_task("T", assigned_to="User", priorty_level="High")
        assert not any(c.request.method == "POST" for c in responses.calls)

    @responses.activate
    def test_custom_field_kwarg_case_insensitive_by_id(self, wb):
        _task_mocks(custom_fields=[{"id": 77, "name": "Priority Level"}])
        wb.create_task("T", assigned_to="User", due_date=datetime.date(2024, 1, 1),
                       priority_level="High")
        body = json.loads(responses.calls[-1].request.body)
        assert body["custom_fields"] == [{"id": 77, "value": "High"}]

    @responses.activate
    def test_no_kwargs_sends_empty_custom_fields(self, wb):
        _task_mocks()
        wb.create_task("T", assigned_to="User", due_date=datetime.date(2024, 1, 1))
        body = json.loads(responses.calls[-1].request.body)
        assert body["custom_fields"] == []


# --- M6 ----------------------------------------------------------------------

class TestCreateTaskAssignee:
    USERS = [{"id": 10, "name": "John Smith"}, {"id": 11, "name": "John Doe"}]

    @responses.activate
    def test_ambiguous_first_name_raises_listing_candidates(self, wb):
        _task_mocks(users=self.USERS)
        with pytest.raises(ValueError, match="Ambiguous assignee 'John'") as ei:
            wb.create_task("T", assigned_to="John")
        assert "John Smith" in str(ei.value) and "John Doe" in str(ei.value)
        assert not any(c.request.method == "POST" for c in responses.calls)

    @responses.activate
    def test_exact_full_name_beats_token_match(self, wb):
        _task_mocks(users=self.USERS + [{"id": 12, "name": "John"}])
        wb.create_task("T", assigned_to="John", due_date=datetime.date(2024, 1, 1))
        assert json.loads(responses.calls[-1].request.body)["assigned_to"] == 12

    @responses.activate
    def test_unique_last_name_resolves(self, wb):
        _task_mocks(users=self.USERS)
        wb.create_task("T", assigned_to="Doe", due_date=datetime.date(2024, 1, 1))
        assert json.loads(responses.calls[-1].request.body)["assigned_to"] == 11

    @responses.activate
    def test_team_by_name(self, wb):
        _task_mocks(users=self.USERS, teams=[{"id": 99, "name": "Ops"}])
        wb.create_task("T", assigned_to="Ops", due_date=datetime.date(2024, 1, 1))
        body = json.loads(responses.calls[-1].request.body)
        assert body["assigned_to_team"] == 99 and body["assigned_to"] is None

    @responses.activate
    def test_linked_to_dict_type_honored(self, wb):
        _task_mocks()
        wb.create_task("T", assigned_to="User", due_date=datetime.date(2024, 1, 1),
                       linked_to=[{"id": 77, "type": "Project"}, {"id": 5}, 6])
        body = json.loads(responses.calls[-1].request.body)
        assert body["linked_to"] == [
            {"id": 77, "type": "Project"},
            {"id": 5, "type": "Contact"},
            {"id": 6, "type": "Contact"},
        ]


# --- L1 ----------------------------------------------------------------------

class TestRetryAfterParsing:
    def _wb(self, monkeypatch):
        slept = []
        monkeypatch.setattr(wealthbox.time, "sleep", slept.append)
        return WealthBox(token="t", rate_limit_retries=1), slept

    @pytest.mark.parametrize("header,expected_sleep", [
        ("-5", 1), ("0", 1), ("Wed, 21 Oct 2015 07:28:00 GMT", 60), ("abc", 60), ("3", 3),
    ])
    @responses.activate
    def test_retry_after_values(self, monkeypatch, header, expected_sleep):
        wb, slept = self._wb(monkeypatch)
        responses.add(responses.GET, f"{BASE_URL}contacts/1", status=429,
                      headers={"Retry-After": header})
        responses.add(responses.GET, f"{BASE_URL}contacts/1", json={"id": 1}, status=200)
        assert wb.get_contact(1) == {"id": 1}
        assert slept == [expected_sleep]

    def test_negative_parses_to_zero(self):
        class R:
            headers = {"Retry-After": "-5"}
        assert WealthBox._retry_after_seconds(R()) == 0

    @responses.activate
    def test_exhausted_still_raises_rate_limit(self, wb):
        responses.add(responses.GET, f"{BASE_URL}contacts/1", status=429,
                      headers={"Retry-After": "-5"})
        with pytest.raises(WealthBoxRateLimitError):
            wb.get_contact(1)


# --- L2 / L3 -----------------------------------------------------------------

class TestPaginationRobustness:
    @pytest.mark.parametrize("meta", [{}, {"total_pages": None}, {"total_pages": "3"}])
    @responses.activate
    def test_bad_total_pages_raises_response_error(self, wb, meta):
        responses.add(responses.GET, f"{BASE_URL}contacts",
                      json={"contacts": [{"id": 1}], "meta": meta}, status=200)
        with pytest.raises(WealthBoxResponseError, match="total_pages"):
            wb.api_request("contacts")

    @responses.activate
    def test_page_failure_cancels_remaining_pages(self):
        wb = WealthBox(token="t", rate_limit_retries=0, page_workers=1)

        def callback(request):
            page = int(request.params["page"])
            if page == 1:
                return 200, {}, json.dumps(_list("contacts", [{"id": 1}], total_pages=10))
            if page == 2:
                return 400, {}, json.dumps({"error": "bad"})
            return 200, {}, json.dumps(_list("contacts", [{"id": page}], total_pages=10))

        responses.add_callback(responses.GET, f"{BASE_URL}contacts", callback=callback)
        with pytest.raises(WealthBoxAPIError):
            wb.api_request("contacts")
        # page 1, page 2 (fails); pages 3..10 cancelled before starting.
        # Allow one in-flight page that may have started before cancellation.
        assert len(responses.calls) <= 3

    @responses.activate
    def test_duplicates_across_pages_removed_first_seen_order(self, wb):
        pages = {
            1: [{"id": 1}, {"id": 2}],
            2: [{"id": 2}, {"id": 3}, {"no_id": True}],
            3: [{"id": 4}, {"no_id": True}],
        }

        def callback(request):
            p = int(request.params["page"])
            return 200, {}, json.dumps(_list("contacts", pages[p], total_pages=3))

        responses.add_callback(responses.GET, f"{BASE_URL}contacts", callback=callback)
        result = wb.api_request("contacts")
        assert result == [{"id": 1}, {"id": 2}, {"id": 3}, {"no_id": True},
                          {"id": 4}, {"no_id": True}]


# --- L4 ----------------------------------------------------------------------

class TestConnectionErrorsWrapped:
    @pytest.mark.parametrize("exc", [
        requests.exceptions.ConnectTimeout("x"),
        requests.exceptions.ReadTimeout("x"),
        requests.exceptions.ConnectionError("x"),
    ])
    @responses.activate
    def test_wrapped_with_cause(self, wb, exc):
        responses.add(responses.GET, f"{BASE_URL}contacts", body=exc)
        with pytest.raises(WealthBoxConnectionError) as ei:
            wb.api_request("contacts", params={"email": "secret@example.com"})
        assert isinstance(ei.value, WealthBoxError)
        assert ei.value.__cause__ is exc
        # Query string (filter PII) is not echoed into the message
        assert "secret" not in str(ei.value)
        assert "/v1/contacts" in str(ei.value)

    def test_exported(self):
        assert "WealthBoxConnectionError" in dir(wealthbox)


# --- L5 ----------------------------------------------------------------------

class TestNullDates:
    ITEMS = [
        {"id": 1, "created_at": "2025-01-01", "updated_at": None},
        {"id": 2, "created_at": None, "updated_at": None},
        {"id": 3, "created_at": "2025-03-01"},
        {"id": 4},
    ]

    def test_filter_by_date_excludes_null(self):
        assert [i["id"] for i in filter_by_date(self.ITEMS, "2024-12-01")] == [1, 3]

    @pytest.mark.parametrize("order,expected", [("desc", [3, 1, 2, 4]), ("asc", [1, 3, 2, 4])])
    def test_sort_and_limit_nulls_last(self, order, expected):
        assert [i["id"] for i in sort_and_limit(self.ITEMS, order=order)] == expected


# --- L6 ----------------------------------------------------------------------

class TestFalsyIdAndCount:
    @pytest.mark.parametrize("bad", [None, 0, ""])
    @responses.activate
    def test_get_comments_requires_id(self, wb, bad):
        with pytest.raises(ValueError):
            wb.get_comments(bad)
        assert len(responses.calls) == 0

    @responses.activate
    def test_get_comments_sends_resource_id(self, wb):
        responses.add(responses.GET, f"{BASE_URL}comments",
                      json=_list("comments", []), status=200)
        wb.get_comments(5, resource_type="task")
        assert responses.calls[0].request.params["resource_id"] == "5"

    @pytest.mark.parametrize("body", [
        {"contacts": []},
        {"contacts": [], "meta": {}},
        {"contacts": [], "meta": {"total_count": None}},
    ])
    @responses.activate
    def test_count_missing_total_raises(self, wb, body):
        responses.add(responses.GET, f"{BASE_URL}contacts", json=body, status=200)
        with pytest.raises(WealthBoxResponseError, match="total_count"):
            wb.count("contacts")

    @responses.activate
    def test_count_zero_is_valid(self, wb):
        responses.add(responses.GET, f"{BASE_URL}contacts",
                      json={"contacts": [], "meta": {"total_count": 0, "total_pages": 0}},
                      status=200)
        assert wb.count("contacts") == 0


# --- L7 ----------------------------------------------------------------------

class TestCustomFieldCacheRefresh:
    OLD = _list("custom_fields", [{"id": 1, "name": "A"}])
    NEW = _list("custom_fields", [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])

    @responses.activate
    def test_unknown_name_refetches_once(self, wb):
        responses.add(responses.GET, f"{BASE_URL}categories/custom_fields", json=self.OLD)
        responses.add(responses.GET, f"{BASE_URL}categories/custom_fields", json=self.NEW)
        wb.build_custom_fields_payload("Contact", {"A": 1})   # primes cache (OLD)
        assert wb.build_custom_fields_payload("Contact", {"B": 2}) == [{"id": 2, "value": 2}]
        assert len(responses.calls) == 2
        # now cached: no further fetch
        wb.build_custom_fields_payload("Contact", {"B": 3})
        assert len(responses.calls) == 2

    @responses.activate
    def test_still_unknown_after_refetch_raises(self, wb):
        responses.add(responses.GET, f"{BASE_URL}categories/custom_fields", json=self.OLD)
        wb.build_custom_fields_payload("Contact", {"A": 1})
        with pytest.raises(ValueError, match="No custom field named 'Z'"):
            wb.build_custom_fields_payload("Contact", {"Z": 1})
        assert len(responses.calls) == 2  # one refetch, not a loop

    @responses.activate
    def test_clear_custom_field_cache(self, wb):
        responses.add(responses.GET, f"{BASE_URL}categories/custom_fields", json=self.OLD)
        wb.build_custom_fields_payload("Contact", {"A": 1})
        wb.build_custom_fields_payload("Task", {"A": 1})
        wb.clear_custom_field_cache("Contact")
        assert "Contact" not in wb._custom_field_cache and "Task" in wb._custom_field_cache
        wb.clear_custom_field_cache()
        assert wb._custom_field_cache == {}


# --- L9 ----------------------------------------------------------------------

def test_api_error_docstring_flags_pii():
    assert "PII" in WealthBoxAPIError.__doc__


@responses.activate
def test_api_error_carries_status_code():
    wb = WealthBox(token="t", max_retries=0)
    responses.add(responses.GET, "https://api.crmworkspace.com/v1/contacts/5",
                  json={"error": "nope"}, status=404)
    with pytest.raises(WealthBoxAPIError) as ei:
        wb.get_contact(5)
    assert ei.value.status_code == 404
