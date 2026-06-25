import datetime
import json
import pytest
import responses
from wealthbox import (
    WealthBox, WealthBoxAPIError, WealthBoxResponseError, WealthBoxRateLimitError,
    filter_by_date, filter_by_tag, normalize_tags, sort_and_limit,
)


BASE_URL = "https://api.crmworkspace.com/v1/"


@pytest.fixture
def wb():
    # Disable rate limit retries in tests to avoid sleeping
    return WealthBox(token="test_token", rate_limit_retries=0)


class TestApiRequest:
    @responses.activate
    def test_single_page_response(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1, "name": "John"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.api_request("contacts")

        assert result == [{"id": 1, "name": "John"}]
        assert len(responses.calls) == 1
        assert "ACCESS_TOKEN" in responses.calls[0].request.headers

    @responses.activate
    def test_pagination_multiple_pages(self, wb):
        # Key each page off ?page= so the concurrent fetch of pages 2..3
        # is deterministic (mirrors the real API).
        for p in (1, 2, 3):
            responses.add(
                responses.GET,
                f"{BASE_URL}contacts",
                json={"contacts": [{"id": p}], "meta": {"total_pages": 3}},
                status=200,
                match=[responses.matchers.query_param_matcher(
                    {"page": str(p), "per_page": "500"}
                )],
            )

        result = wb.api_request("contacts")

        assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert len(responses.calls) == 3

    @responses.activate
    def test_pagination_concurrent_preserves_order(self, wb):
        # Register each page keyed off the ?page= param so order is
        # deterministic regardless of which worker thread arrives first.
        total = 5
        for p in range(1, total + 1):
            responses.add(
                responses.GET,
                f"{BASE_URL}contacts",
                json={"contacts": [{"id": p}], "meta": {"total_pages": total}},
                status=200,
                match=[responses.matchers.query_param_matcher(
                    {"page": str(p), "per_page": "500"}
                )],
            )

        result = wb.api_request("contacts")

        # Reassembled in page order even though pages 2..5 ran concurrently
        assert [r["id"] for r in result] == [1, 2, 3, 4, 5]

    @responses.activate
    def test_max_results_stops_early(self, wb):
        # 10 pages of 2 records each; max_results=3 should fetch only
        # page 1 (2 recs) + page 2 (enough), never pages 3..10.
        for p in range(1, 11):
            responses.add(
                responses.GET,
                f"{BASE_URL}contacts",
                json={
                    "contacts": [{"id": p * 10 + 1}, {"id": p * 10 + 2}],
                    "meta": {"total_pages": 10},
                },
                status=200,
                match=[responses.matchers.query_param_matcher(
                    {"page": str(p), "per_page": "500"}
                )],
            )

        result = wb.api_request("contacts", max_results=3)

        assert len(result) == 3
        assert len(responses.calls) == 2  # only pages 1 and 2 fetched

    @responses.activate
    def test_max_results_within_first_page(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1}, {"id": 2}, {"id": 3}],
                "meta": {"total_pages": 4},
            },
            status=200,
        )

        result = wb.api_request("contacts", max_results=2)

        assert result == [{"id": 1}, {"id": 2}]
        assert len(responses.calls) == 1  # never fetched page 2

    @responses.activate
    def test_count_single_request(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={"contacts": [{"id": 1}], "meta": {"total_count": 4022, "total_pages": 4022}},
            status=200,
        )

        assert wb.count("contacts") == 4022
        assert len(responses.calls) == 1
        assert responses.calls[0].request.params["per_page"] == "1"

    @responses.activate
    def test_response_without_meta(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}me",
            json={"current_user": {"id": 123}},
            status=200
        )

        result = wb.api_request("me")

        assert result == {"current_user": {"id": 123}}

    @responses.activate
    def test_custom_extract_key(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [{"id": 1, "content": "Note"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.api_request("notes", extract_key="status_updates")

        assert result == [{"id": 1, "content": "Note"}]

    @responses.activate
    def test_json_decode_error(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            body="not json",
            status=200
        )

        with pytest.raises(WealthBoxResponseError) as exc_info:
            wb.api_request("contacts")

        assert "Failed to decode JSON" in str(exc_info.value)
        assert exc_info.value.response_text == "not json"

    @responses.activate
    def test_missing_key_error(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "wrong_key": [],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_request("contacts")

        assert "Expected key 'contacts' not found" in str(exc_info.value)

    @responses.activate
    def test_rate_limit_error(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            status=429,
            headers={"Retry-After": "60"}
        )

        with pytest.raises(WealthBoxRateLimitError) as exc_info:
            wb.api_request("contacts")

        assert exc_info.value.retry_after == 60

    @pytest.mark.parametrize("key,filter_value,must_contain,must_not_contain", [
        # Lists serialize as tags[]= because plain tags=a&tags=b is last-wins
        # in the WB API.
        ("tags", ["VIP", "10M"], ["tags%5B%5D=VIP", "tags%5B%5D=10M"], ["tags=VIP", "tags=10M"]),
        # Tuples behave the same as lists.
        ("tags", ("VIP", "10M"), ["tags%5B%5D=VIP", "tags%5B%5D=10M"], ["tags=VIP", "tags=10M"]),
        # Scalars pass through unchanged.
        ("tags", "VIP", ["tags=VIP"], ["tags%5B%5D="]),
        # Pre-bracketed key must not double-bracket.
        ("tags[]", ["VIP", "10M"], ["tags%5B%5D=VIP"], ["tags%5B%5D%5B%5D"]),
    ])
    @responses.activate
    def test_list_filter_serialization(self, wb, key, filter_value, must_contain, must_not_contain):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={"contacts": [], "meta": {"total_pages": 1}},
            status=200,
        )

        wb.api_request("contacts", params={key: filter_value})

        sent_url = responses.calls[0].request.url
        for fragment in must_contain:
            assert fragment in sent_url, f"missing {fragment!r} in {sent_url!r}"
        for fragment in must_not_contain:
            assert fragment not in sent_url, f"unexpected {fragment!r} in {sent_url!r}"


class TestApiPut:
    @responses.activate
    def test_put_success(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}contacts/123",
            json={"id": 123, "name": "Updated"},
            status=200
        )

        result = wb.api_put("contacts/123", {"name": "Updated"})

        assert result == {"id": 123, "name": "Updated"}
        assert responses.calls[0].request.headers["ACCESS_TOKEN"] == "test_token"

    @responses.activate
    def test_put_json_error(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}contacts/123",
            body="not json",
            status=200
        )

        with pytest.raises(WealthBoxResponseError) as exc_info:
            wb.api_put("contacts/123", {"name": "Updated"})

        assert "Failed to decode JSON" in str(exc_info.value)


class TestApiPost:
    @responses.activate
    def test_post_success(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 456, "name": "New Task"},
            status=201
        )

        result = wb.api_post("tasks", {"name": "New Task"})

        assert result == {"id": 456, "name": "New Task"}

    @responses.activate
    def test_post_json_error(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            body="server error",
            status=500
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_post("tasks", {"name": "New Task"})

        # Status code and raw body both surface in the message
        assert "500" in str(exc_info.value)
        assert "server error" in str(exc_info.value)


class TestGetTasks:
    @responses.activate
    def test_default_params(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200
        )

        wb.get_tasks()

        request_params = responses.calls[0].request.params
        assert request_params["resource_type"] == "contact"
        assert request_params["completed"] == "false"

    @responses.activate
    def test_override_params(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200
        )

        wb.get_tasks(resource_type="opportunity", assigned_to=123)

        request_params = responses.calls[0].request.params
        assert request_params["resource_type"] == "opportunity"
        assert request_params["assigned_to"] == "123"

    @responses.activate
    def test_other_filters(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200
        )

        wb.get_tasks(other_filters={"custom_field": "value"})

        request_params = responses.calls[0].request.params
        assert request_params["custom_field"] == "value"

    @responses.activate
    def test_completed_boolean_conversion(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200
        )

        wb.get_tasks(completed=False)

        request_params = responses.calls[0].request.params
        assert request_params["completed"] == "false"


class TestGetWorkflows:
    @responses.activate
    def test_default_params(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows",
            json={"workflows": [], "meta": {"total_pages": 1}},
            status=200
        )

        wb.get_workflows()

        request_params = responses.calls[0].request.params
        assert request_params["resource_type"] == "contact"
        assert request_params["status"] == "active"

    @responses.activate
    def test_override_status(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows",
            json={"workflows": [], "meta": {"total_pages": 1}},
            status=200
        )

        wb.get_workflows(status="completed")

        request_params = responses.calls[0].request.params
        assert request_params["status"] == "completed"


class TestEnhanceUserInfo:
    def test_dict_with_creator(self, wb):
        user_map = {1: "John Doe", 2: "Jane Smith"}
        data = {"id": 100, "creator": 1, "name": "Task"}

        result = wb.enhance_user_info(data, user_map)

        assert result["creator"] == "John Doe"

    def test_dict_with_assigned_to(self, wb):
        user_map = {1: "John Doe"}
        data = {"id": 100, "assigned_to": 1}

        result = wb.enhance_user_info(data, user_map)

        assert result["assigned_to"] == "John Doe"

    def test_nested_list(self, wb):
        user_map = {1: "John", 2: "Jane"}
        data = [
            {"creator": 1, "items": [{"creator": 2}]}
        ]

        result = wb.enhance_user_info(data, user_map)

        assert result[0]["creator"] == "John"
        assert result[0]["items"][0]["creator"] == "Jane"

    def test_unknown_user_preserved(self, wb):
        user_map = {1: "John"}
        data = {"creator": 999}

        result = wb.enhance_user_info(data, user_map)

        assert result["creator"] == 999

    def test_non_dict_list_passthrough(self, wb):
        assert wb.enhance_user_info("string", {}) == "string"
        assert wb.enhance_user_info(123, {}) == 123
        assert wb.enhance_user_info(None, {}) is None


class TestMakeUserMap:
    @responses.activate
    def test_full_method(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={
                "users": [{"id": 1, "name": "John Doe", "email": "john@example.com"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.make_user_map(method="full")

        assert result[1] == "1; John Doe; john@example.com"

    @responses.activate
    def test_name_method(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={
                "users": [{"id": 1, "name": "John Doe", "email": "john@example.com"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.make_user_map(method="name")

        assert result[1] == "John Doe"

    @responses.activate
    def test_first_name_method(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={
                "users": [{"id": 1, "name": "John Doe", "email": "john@example.com"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.make_user_map(method="first_name")

        assert result[1] == "John"

    @responses.activate
    def test_invalid_method(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={
                "users": [{"id": 1, "name": "John", "email": "john@example.com"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        with pytest.raises(ValueError) as exc_info:
            wb.make_user_map(method="invalid")

        assert "must be one of" in str(exc_info.value)


class TestCreateTaskDetailed:
    @responses.activate
    def test_creates_task_with_defaults(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}me",
            json={"current_user": {"id": 99}},
            status=200
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 1, "name": "Test Task"},
            status=201
        )

        result = wb.create_task_detailed("Test Task")

        assert result == {"id": 1, "name": "Test Task"}
        post_body = responses.calls[1].request.body
        assert b'"assigned_to": 99' in post_body

    @responses.activate
    def test_date_formatting(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 1},
            status=201
        )

        test_date = datetime.date(2024, 6, 15)
        wb.create_task_detailed("Task", due_date=test_date, assigned_to=1)

        post_body = responses.calls[0].request.body
        assert b"2024-06-15T00:00:00Z" in post_body


class TestCreateTask:
    @responses.activate
    def test_assigns_to_user_by_name(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={
                "users": [{"id": 10, "name": "John Doe"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}teams",
            json={"teams": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/task_categories",
            json={"task_categories": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/custom_fields",
            json={"custom_fields": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 1},
            status=201
        )

        wb.create_task("My Task", assigned_to="John Doe", due_date=datetime.date(2024, 1, 1))

        post_body = responses.calls[-1].request.body
        assert b'"assigned_to": 10' in post_body

    @responses.activate
    def test_unknown_assignee_raises(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={"users": [{"id": 10, "name": "John Doe"}], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}teams",
            json={"teams": [], "meta": {"total_pages": 1}},
            status=200
        )

        # A typo'd name must raise, not silently assign to the token owner
        with pytest.raises(ValueError, match="No user or team named 'Jon Doh'"):
            wb.create_task("My Task", assigned_to="Jon Doh")

    @responses.activate
    def test_unknown_category_raises(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={"users": [{"id": 10, "name": "John Doe"}], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}teams",
            json={"teams": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/task_categories",
            json={
                "task_categories": [{"id": 5, "name": "Follow Up"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        with pytest.raises(ValueError, match="No task category named 'Nope'"):
            wb.create_task("My Task", category="Nope")

    @responses.activate
    def test_linked_to_single_id(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={"users": [{"id": 1, "name": "User"}], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}teams",
            json={"teams": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/task_categories",
            json={"task_categories": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/custom_fields",
            json={"custom_fields": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 1},
            status=201
        )

        wb.create_task("Task", linked_to=555, assigned_to="User", due_date=datetime.date(2024, 1, 1))

        post_body = responses.calls[-1].request.body.decode()
        assert '"id": 555' in post_body
        assert '"type": "Contact"' in post_body

    @responses.activate
    def test_linked_to_list_of_dicts(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={"users": [{"id": 1, "name": "User"}], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}teams",
            json={"teams": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/task_categories",
            json={"task_categories": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/custom_fields",
            json={"custom_fields": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 1},
            status=201
        )

        wb.create_task("Task", linked_to=[{"id": 100, "extra": "ignored"}],
                       assigned_to="User", due_date=datetime.date(2024, 1, 1))

        post_body = responses.calls[-1].request.body.decode()
        assert '"id": 100' in post_body
        assert "extra" not in post_body

    @responses.activate
    def test_category_by_name(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={"users": [{"id": 1, "name": "User"}], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}teams",
            json={"teams": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/task_categories",
            json={
                "task_categories": [{"id": 50, "name": "Follow Up"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/custom_fields",
            json={"custom_fields": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 1},
            status=201
        )

        wb.create_task("Task", category="Follow Up", assigned_to="User",
                       due_date=datetime.date(2024, 1, 1))

        post_body = responses.calls[-1].request.body.decode()
        assert '"category": 50' in post_body

    @responses.activate
    def test_custom_fields_from_kwargs(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}users",
            json={"users": [{"id": 1, "name": "User"}], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}teams",
            json={"teams": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/task_categories",
            json={"task_categories": [], "meta": {"total_pages": 1}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}categories/custom_fields",
            json={
                "custom_fields": [{"name": "Priority Level"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}tasks",
            json={"id": 1},
            status=201
        )

        wb.create_task("Task", assigned_to="User", due_date=datetime.date(2024, 1, 1),
                       Priority_Level="High")

        post_body = responses.calls[-1].request.body.decode()
        assert "Priority Level" in post_body
        assert "High" in post_body


class TestGetNotes:
    @responses.activate
    def test_uses_status_updates_key(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [{"id": 1, "content": "A note"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.get_notes(resource_id=100)

        assert result == [{"id": 1, "content": "A note"}]


class TestGetMyUserId:
    @responses.activate
    def test_returns_user_id(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}me",
            json={"current_user": {"id": 42}},
            status=200
        )

        result = wb.get_my_user_id()

        assert result == 42
        assert wb.user_id == 42


class TestGetMyTasks:
    @responses.activate
    def test_filters_by_assigned_to(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}me",
            json={"current_user": {"id": 42}},
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks",
            json={"tasks": [], "meta": {"total_pages": 1}},
            status=200
        )

        wb.get_my_tasks()

        request_params = responses.calls[1].request.params
        assert request_params["assigned_to"] == "42"
        assert "resource_id" not in request_params


class TestApiDelete:
    @responses.activate
    def test_delete_success_204(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}contacts/123",
            status=204
        )

        result = wb.api_delete("contacts/123")

        assert result is True

    @responses.activate
    def test_delete_success_200(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}contacts/123",
            status=200
        )

        result = wb.api_delete("contacts/123")

        assert result is True

    @responses.activate
    def test_delete_failure(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}contacts/123",
            json={"error": "Not found"},
            status=404
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_delete("contacts/123")

        assert "DELETE /contacts/123" in str(exc_info.value)
        assert "404" in str(exc_info.value)
        assert "Not found" in str(exc_info.value)

    @responses.activate
    def test_delete_rate_limit(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}contacts/123",
            status=429,
            headers={"Retry-After": "30"}
        )

        with pytest.raises(WealthBoxRateLimitError) as exc_info:
            wb.api_delete("contacts/123")

        assert exc_info.value.retry_after == 30


class TestApiGetSingle:
    @responses.activate
    def test_get_single_success(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/123",
            json={"id": 123, "name": "John Doe"},
            status=200
        )

        result = wb.api_get_single("contacts/123")

        assert result == {"id": 123, "name": "John Doe"}

    @responses.activate
    def test_get_single_json_error(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/123",
            body="not json",
            status=200
        )

        with pytest.raises(WealthBoxResponseError):
            wb.api_get_single("contacts/123")


class TestContactEndpoints:
    @responses.activate
    def test_get_contact(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/123",
            json={"id": 123, "first_name": "John"},
            status=200
        )

        result = wb.get_contact(123)

        assert result == {"id": 123, "first_name": "John"}

    @responses.activate
    def test_create_contact(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}contacts",
            json={"id": 456, "first_name": "Jane"},
            status=201
        )

        result = wb.create_contact({"first_name": "Jane", "last_name": "Doe"})

        assert result == {"id": 456, "first_name": "Jane"}

    @responses.activate
    def test_delete_contact(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}contacts/123",
            status=204
        )

        result = wb.delete_contact(123)

        assert result is True


class TestTaskEndpoints:
    @responses.activate
    def test_get_task(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}tasks/123",
            json={"id": 123, "name": "Task 1"},
            status=200
        )

        result = wb.get_task(123)

        assert result == {"id": 123, "name": "Task 1"}

    @responses.activate
    def test_update_task(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}tasks/123",
            json={"id": 123, "name": "Updated Task"},
            status=200
        )

        result = wb.update_task(123, {"name": "Updated Task"})

        assert result == {"id": 123, "name": "Updated Task"}

    @responses.activate
    def test_delete_task(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}tasks/123",
            status=204
        )

        result = wb.delete_task(123)

        assert result is True


class TestWorkflowEndpoints:
    @responses.activate
    def test_get_workflow(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows/123",
            json={"id": 123, "name": "Onboarding"},
            status=200
        )

        result = wb.get_workflow(123)

        assert result == {"id": 123, "name": "Onboarding"}

    @responses.activate
    def test_create_workflow(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}workflows",
            json={"id": 456, "name": "New Workflow"},
            status=201
        )

        result = wb.create_workflow({"template_id": 1, "linked_to": [{"id": 100}]})

        assert result == {"id": 456, "name": "New Workflow"}

    @responses.activate
    def test_delete_workflow(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}workflows/123",
            status=204
        )

        result = wb.delete_workflow(123)

        assert result is True

    @responses.activate
    def test_get_workflow_templates(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflow_templates",
            json={
                "workflow_templates": [{"id": 1, "name": "Template 1"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.get_workflow_templates()

        assert result == [{"id": 1, "name": "Template 1"}]

    @responses.activate
    def test_complete_workflow_step(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}workflows/55/steps/123",
            json={"id": 123, "completed_at": "2026-06-25"},
            status=200
        )

        result = wb.complete_workflow_step(55, 123)

        assert result == {"id": 123, "completed_at": "2026-06-25"}
        # Step is addressed under its workflow, with a {"complete": true} body.
        assert json.loads(responses.calls[0].request.body) == {"complete": True}

    @responses.activate
    def test_complete_workflow_step_with_outcome(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}workflows/55/steps/123",
            json={"id": 123, "completed_at": "2026-06-25"},
            status=200
        )

        wb.complete_workflow_step(55, 123, workflow_outcome_id=7)

        assert json.loads(responses.calls[0].request.body) == {
            "complete": True, "workflow_outcome_id": 7
        }

    @responses.activate
    def test_revert_workflow_step(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}workflows/55/steps/123",
            json={"id": 123, "completed_at": ""},
            status=200
        )

        result = wb.revert_workflow_step(55, 123)

        assert result == {"id": 123, "completed_at": ""}
        assert json.loads(responses.calls[0].request.body) == {"revert": True}


class TestEventEndpoints:
    @responses.activate
    def test_get_event(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}events/123",
            json={"id": 123, "name": "Meeting"},
            status=200
        )

        result = wb.get_event(123)

        assert result == {"id": 123, "name": "Meeting"}

    @responses.activate
    def test_create_event(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}events",
            json={"id": 456, "name": "New Event"},
            status=201
        )

        result = wb.create_event({"name": "New Event", "starts_at": "2024-01-01"})

        assert result == {"id": 456, "name": "New Event"}

    @responses.activate
    def test_update_event(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}events/123",
            json={"id": 123, "name": "Updated Event"},
            status=200
        )

        result = wb.update_event(123, {"name": "Updated Event"})

        assert result == {"id": 123, "name": "Updated Event"}

    @responses.activate
    def test_delete_event(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}events/123",
            status=204
        )

        result = wb.delete_event(123)

        assert result is True


class TestOpportunityEndpoints:
    @responses.activate
    def test_get_opportunity(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}opportunities/123",
            json={"id": 123, "name": "Deal"},
            status=200
        )

        result = wb.get_opportunity(123)

        assert result == {"id": 123, "name": "Deal"}

    @responses.activate
    def test_create_opportunity(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}opportunities",
            json={"id": 456, "name": "New Deal"},
            status=201
        )

        result = wb.create_opportunity({"name": "New Deal", "stage_id": 1})

        assert result == {"id": 456, "name": "New Deal"}

    @responses.activate
    def test_update_opportunity(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}opportunities/123",
            json={"id": 123, "name": "Updated Deal"},
            status=200
        )

        result = wb.update_opportunity(123, {"name": "Updated Deal"})

        assert result == {"id": 123, "name": "Updated Deal"}

    @responses.activate
    def test_delete_opportunity(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}opportunities/123",
            status=204
        )

        result = wb.delete_opportunity(123)

        assert result is True


class TestNoteEndpoints:
    @responses.activate
    def test_get_note(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes/123",
            json={"id": 123, "content": "Note content"},
            status=200
        )

        result = wb.get_note(123)

        assert result == {"id": 123, "content": "Note content"}

    @responses.activate
    def test_create_note(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}notes",
            json={"id": 456, "content": "New note"},
            status=201
        )

        result = wb.create_note({"content": "New note", "linked_to": [{"id": 100}]})

        assert result == {"id": 456, "content": "New note"}

    @responses.activate
    def test_update_note(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}notes/123",
            json={"id": 123, "content": "Updated note"},
            status=200
        )

        result = wb.update_note(123, {"content": "Updated note"})

        assert result == {"id": 123, "content": "Updated note"}


class TestProjectEndpoints:
    @responses.activate
    def test_get_projects(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}projects",
            json={
                "projects": [{"id": 1, "name": "Project 1"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.get_projects()

        assert result == [{"id": 1, "name": "Project 1"}]

    @responses.activate
    def test_get_project(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}projects/123",
            json={"id": 123, "name": "Project"},
            status=200
        )

        result = wb.get_project(123)

        assert result == {"id": 123, "name": "Project"}

    @responses.activate
    def test_create_project(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}projects",
            json={"id": 456, "name": "New Project"},
            status=201
        )

        result = wb.create_project({"name": "New Project"})

        assert result == {"id": 456, "name": "New Project"}

    @responses.activate
    def test_update_project(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}projects/123",
            json={"id": 123, "name": "Updated Project"},
            status=200
        )

        result = wb.update_project(123, {"name": "Updated Project"})

        assert result == {"id": 123, "name": "Updated Project"}

    @responses.activate
    def test_delete_project(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}projects/123",
            status=204
        )

        result = wb.delete_project(123)

        assert result is True


class TestActivityEndpoint:
    @responses.activate
    def test_get_activity(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}activity",
            json={
                "activity": [{"id": 1, "type": "contact_created"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.get_activity()

        assert result == [{"id": 1, "type": "contact_created"}]


class TestContactRolesEndpoint:
    @responses.activate
    def test_get_contact_roles(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contact_roles",
            json={
                "contact_roles": [{"id": 1, "name": "Primary"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.get_contact_roles()

        assert result == [{"id": 1, "name": "Primary"}]


class TestUserGroupsEndpoint:
    @responses.activate
    def test_get_user_groups(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}user_groups",
            json={
                "user_groups": [{"id": 1, "name": "Admins"}],
                "meta": {"total_pages": 1}
            },
            status=200
        )

        result = wb.get_user_groups()

        assert result == [{"id": 1, "name": "Admins"}]


class TestHouseholdMembersEndpoints:
    @responses.activate
    def test_add_household_member(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}household_members",
            json={"household_id": 100, "contact_id": 200},
            status=201
        )

        result = wb.add_household_member(100, 200)

        assert result == {"household_id": 100, "contact_id": 200}
        request_body = responses.calls[0].request.body
        assert b'"household_id": 100' in request_body
        assert b'"contact_id": 200' in request_body

    @responses.activate
    def test_remove_household_member(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}household_members/100/200",
            status=204
        )

        result = wb.remove_household_member(100, 200)

        assert result is True


class TestResolveHousehold:
    @responses.activate
    def test_household_contact_resolves_members(self, wb):
        household = {
            "id": 1, "type": "Household", "name": "Smith Household",
            "members": [{"id": 10}, {"id": 11}],
        }
        for mid in (10, 11):
            responses.add(
                responses.GET, f"{BASE_URL}contacts/{mid}",
                json={"id": mid, "name": f"Member {mid}"}, status=200,
            )

        members, hh = wb.resolve_household(household)

        assert {m["id"] for m in members} == {10, 11}
        assert hh == {"id": 1, "name": "Smith Household"}

    @responses.activate
    def test_member_contact_fetches_its_household(self, wb):
        person = {"id": 10, "type": "Person", "household": {"id": 1, "name": "Smith"}}
        responses.add(
            responses.GET, f"{BASE_URL}contacts/1",
            json={"id": 1, "type": "Household", "name": "Smith Household",
                  "members": [{"id": 10}]}, status=200,
        )
        responses.add(
            responses.GET, f"{BASE_URL}contacts/10",
            json={"id": 10, "name": "John Smith"}, status=200,
        )

        members, hh = wb.resolve_household(person)

        assert [m["id"] for m in members] == [10]
        assert hh["id"] == 1

    def test_contact_with_no_household(self, wb):
        person = {"id": 10, "type": "Person"}
        members, hh = wb.resolve_household(person)
        assert members == [person]
        assert hh is None


class TestCategoryWrappers:
    @pytest.mark.parametrize("method,cat_type", [
        ("get_opportunity_stages", "opportunity_stages"),
        ("get_note_categories", "note_categories"),
        ("get_event_categories", "event_categories"),
        ("get_project_statuses", "project_statuses"),
        ("get_task_categories", "task_categories"),
        ("get_contact_types", "contact_types"),
    ])
    @responses.activate
    def test_wrapper_hits_category_endpoint(self, wb, method, cat_type):
        responses.add(
            responses.GET, f"{BASE_URL}categories/{cat_type}",
            json={cat_type: [{"id": 1, "name": "X"}], "meta": {"total_pages": 1}},
            status=200,
        )

        result = getattr(wb, method)()

        assert result == [{"id": 1, "name": "X"}]
        assert f"categories/{cat_type}" in responses.calls[0].request.url

    @responses.activate
    def test_add_household_member_invalid_contact(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}household_members",
            json={"error": "Invalid contact"},
            status=422
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.add_household_member(100, 999)
        assert exc_info.value.response == {"error": "Invalid contact"}

    @responses.activate
    def test_add_household_member_not_found(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}household_members",
            json={"error": "Not found"},
            status=404
        )

        with pytest.raises(WealthBoxAPIError):
            wb.add_household_member(999, 200)

    @responses.activate
    def test_add_household_member_rate_limit(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}household_members",
            json={},
            status=429,
            headers={"Retry-After": "5"}
        )

        with pytest.raises(WealthBoxRateLimitError) as exc_info:
            wb.add_household_member(100, 200)
        assert exc_info.value.retry_after == 5

    @responses.activate
    def test_add_household_member_non_json_error(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}household_members",
            body="Internal Server Error",
            status=500,
            content_type="text/plain"
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.add_household_member(100, 200)
        assert "500" in str(exc_info.value)
        assert "Internal Server Error" in str(exc_info.value)

    @responses.activate
    def test_remove_household_member_not_found(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}household_members/100/999",
            json={"error": "Not found"},
            status=404
        )

        with pytest.raises(WealthBoxAPIError):
            wb.remove_household_member(100, 999)

    @responses.activate
    def test_remove_household_member_rate_limit(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}household_members/100/200",
            json={},
            status=429,
            headers={"Retry-After": "10"}
        )

        with pytest.raises(WealthBoxRateLimitError) as exc_info:
            wb.remove_household_member(100, 200)
        assert exc_info.value.retry_after == 10

    @responses.activate
    def test_remove_household_member_non_json_error(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}household_members/100/200",
            body="Server Error",
            status=500,
            content_type="text/plain"
        )

        with pytest.raises(WealthBoxAPIError):
            wb.remove_household_member(100, 200)

    @responses.activate
    def test_remove_household_member_returns_true_on_200(self, wb):
        responses.add(
            responses.DELETE,
            f"{BASE_URL}household_members/100/200",
            status=200
        )

        result = wb.remove_household_member(100, 200)

        assert result is True


# ---------------------------------------------------------------------------
# Filter utility tests
# ---------------------------------------------------------------------------


class TestFilterByDate:
    def test_filters_by_created_at(self):
        items = [
            {"id": 1, "created_at": "2024-01-01", "updated_at": "2024-01-01"},
            {"id": 2, "created_at": "2025-06-01", "updated_at": "2025-06-01"},
        ]
        result = filter_by_date(items, "2025-01-01")
        assert [i["id"] for i in result] == [2]

    def test_filters_by_updated_at(self):
        items = [
            {"id": 1, "created_at": "2024-01-01", "updated_at": "2025-02-01"},
        ]
        result = filter_by_date(items, "2025-01-01")
        assert len(result) == 1

    def test_empty_list(self):
        assert filter_by_date([], "2025-01-01") == []

    def test_custom_date_fields(self):
        items = [{"id": 1, "due_date": "2025-06-01"}]
        result = filter_by_date(items, "2025-01-01", date_fields=("due_date",))
        assert len(result) == 1


class TestFilterByTag:
    def test_matches_tag(self):
        items = [
            {"id": 1, "tags": [{"name": "VIP"}]},
            {"id": 2, "tags": [{"name": "other"}]},
        ]
        result = filter_by_tag(items, "VIP")
        assert [i["id"] for i in result] == [1]

    def test_case_insensitive(self):
        items = [{"id": 1, "tags": [{"name": "Restriction"}]}]
        assert len(filter_by_tag(items, "restriction")) == 1
        assert len(filter_by_tag(items, "RESTRICTION")) == 1

    def test_no_match(self):
        items = [{"id": 1, "tags": [{"name": "VIP"}]}]
        assert filter_by_tag(items, "nonexistent") == []

    def test_no_tags_key(self):
        items = [{"id": 1}]
        assert filter_by_tag(items, "VIP") == []


class TestSortAndLimit:
    def test_desc_order(self):
        items = [
            {"id": 1, "created_at": "2024-01-01"},
            {"id": 2, "created_at": "2025-01-01"},
        ]
        result = sort_and_limit(items, order="desc")
        assert result[0]["id"] == 2

    def test_asc_order(self):
        items = [
            {"id": 1, "created_at": "2025-01-01"},
            {"id": 2, "created_at": "2024-01-01"},
        ]
        result = sort_and_limit(items, order="asc")
        assert result[0]["id"] == 2

    def test_limit(self):
        items = [{"id": i, "created_at": f"2024-0{i}-01"} for i in range(1, 6)]
        result = sort_and_limit(items, limit=2)
        assert len(result) == 2

    def test_no_limit_returns_all(self):
        items = [{"id": i, "created_at": f"2024-0{i}-01"} for i in range(1, 6)]
        result = sort_and_limit(items)
        assert len(result) == 5

    def test_custom_key(self):
        items = [
            {"id": 1, "updated_at": "2025-01-01"},
            {"id": 2, "updated_at": "2024-01-01"},
        ]
        result = sort_and_limit(items, order="asc", key="updated_at")
        assert result[0]["id"] == 2


# ---------------------------------------------------------------------------
# Extended method tests
# ---------------------------------------------------------------------------


class TestGetWorkflowsAssignedTo:
    @responses.activate
    def test_without_assigned_to(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows",
            json={
                "workflows": [
                    {"id": 1, "workflow_steps": [{"assigned_to": 10}]},
                    {"id": 2, "workflow_steps": [{"assigned_to": 20}]},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_workflows()
        assert len(result) == 2

    @responses.activate
    def test_with_assigned_to_filters(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows",
            json={
                "workflows": [
                    {"id": 1, "workflow_steps": [
                        {"id": 10, "assigned_to": 100},
                        {"id": 11, "assigned_to": 200},
                    ]},
                    {"id": 2, "workflow_steps": [
                        {"id": 20, "assigned_to": 200},
                    ]},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_workflows(assigned_to=100)
        assert len(result) == 1
        assert result[0]["id"] == 1
        assert len(result[0]["workflow_steps"]) == 1
        assert result[0]["workflow_steps"][0]["assigned_to"] == 100

    @responses.activate
    def test_assigned_to_no_match(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}workflows",
            json={
                "workflows": [
                    {"id": 1, "workflow_steps": [{"assigned_to": 100}]},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_workflows(assigned_to=999)
        assert result == []


class TestGetNotesFiltered:
    @responses.activate
    def test_since_date_filters(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 1, "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                    {"id": 2, "created_at": "2025-06-01", "updated_at": "2025-06-01"},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_notes(resource_id=42, since_date="2025-01-01")
        assert len(result) == 1
        assert result[0]["id"] == 2

    @responses.activate
    def test_tag_filter(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 1, "tags": [{"name": "VIP"}], "created_at": "2024-01-01"},
                    {"id": 2, "tags": [], "created_at": "2024-02-01"},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_notes(resource_id=42, tag="VIP")
        assert len(result) == 1
        assert result[0]["id"] == 1

    @responses.activate
    def test_limit(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": i, "created_at": f"2024-0{i}-01"} for i in range(1, 6)
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_notes(resource_id=42, order="desc", limit=2)
        assert len(result) == 2

    @responses.activate
    def test_no_filter_params_unchanged(self, wb):
        """Without filter params, behavior is identical to before."""
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 1, "created_at": "2024-01-01"},
                    {"id": 2, "created_at": "2024-02-01"},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_notes(resource_id=42)
        assert len(result) == 2


class TestSearchNotesByTag:
    @responses.activate
    def test_finds_notes_with_tag(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 1, "tags": [{"name": "restriction"}], "created_at": "2024-06-01"},
                    {"id": 2, "tags": [], "created_at": "2024-07-01"},
                    {"id": 3, "tags": [{"name": "restriction"}], "created_at": "2024-08-01"},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.search_notes_by_tag("restriction")
        assert len(result) == 2
        assert result[0]["id"] == 3  # desc order

    @responses.activate
    def test_with_since_date(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 1, "tags": [{"name": "VIP"}], "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                    {"id": 2, "tags": [{"name": "VIP"}], "created_at": "2025-06-01", "updated_at": "2025-06-01"},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.search_notes_by_tag("VIP", since_date="2025-01-01")
        assert len(result) == 1
        assert result[0]["id"] == 2

    @responses.activate
    def test_limit(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": i, "tags": [{"name": "t"}], "created_at": f"2024-0{i}-01"}
                    for i in range(1, 6)
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.search_notes_by_tag("t", limit=2)
        assert len(result) == 2


class TestGetContactActivity:
    @responses.activate
    def test_returns_notes_desc(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 1, "created_at": "2024-01-01"},
                    {"id": 2, "created_at": "2025-01-01"},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_contact_activity(contact_id=42)
        assert result[0]["id"] == 2  # most recent first

    @responses.activate
    def test_limit(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": i, "created_at": f"2024-0{i}-01"} for i in range(1, 6)
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_contact_activity(contact_id=42, limit=2)
        assert len(result) == 2

    @responses.activate
    def test_since_date(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [
                    {"id": 1, "created_at": "2024-01-01", "updated_at": "2024-01-01"},
                    {"id": 2, "created_at": "2025-06-01", "updated_at": "2025-06-01"},
                ],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_contact_activity(contact_id=42, since_date="2025-01-01")
        assert len(result) == 1
        assert result[0]["id"] == 2

    @responses.activate
    def test_include_comments(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [{"id": 1, "created_at": "2024-01-01"}],
                "meta": {"total_pages": 1}
            },
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}comments",
            json={
                "comments": [{"id": 99, "body": "a comment"}],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_contact_activity(contact_id=42, include_comments=True)
        assert "comments" in result[0]
        assert result[0]["comments"][0]["id"] == 99

    @responses.activate
    def test_no_comments_by_default(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}notes",
            json={
                "status_updates": [{"id": 1, "created_at": "2024-01-01"}],
                "meta": {"total_pages": 1}
            },
        )
        result = wb.get_contact_activity(contact_id=42)
        assert "comments" not in result[0]


class TestErrorSurfacing:
    """Non-2xx responses must surface status, endpoint, and body in str(exc).

    Per the hardening PRD: a failed call should be self-diagnosing on the
    first failure — the WealthBox validation body (which names the offending
    field) belongs in the exception message, not only on .response.
    """

    @responses.activate
    def test_post_400_message_includes_body(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}notes",
            json={"tags": ["is invalid"]},
            status=400,
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_post("notes", {"content": "hi"})

        msg = str(exc_info.value)
        assert "POST /notes" in msg
        assert "400" in msg
        assert "is invalid" in msg
        assert exc_info.value.response == {"tags": ["is invalid"]}

    @responses.activate
    def test_put_422_message_includes_body(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}contacts/1",
            json={"email_addresses": ["kind must be lowercase"]},
            status=422,
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_put("contacts/1", {"first_name": "A"})

        msg = str(exc_info.value)
        assert "PUT /contacts/1" in msg
        assert "422" in msg
        assert "kind must be lowercase" in msg

    @responses.activate
    def test_get_single_404_raises_instead_of_returning_error_json(self, wb):
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts/999",
            json={"error": "Record not found"},
            status=404,
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_get_single("contacts/999")

        msg = str(exc_info.value)
        assert "GET /contacts/999" in msg
        assert "404" in msg
        assert "Record not found" in msg

    @responses.activate
    def test_api_request_400_raises_with_body(self, wb):
        # Previously a 4xx here fell through to a misleading
        # "Expected key 'contacts' not found in response"
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={"error": "bad filter"},
            status=400,
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_request("contacts")

        msg = str(exc_info.value)
        assert "GET /contacts" in msg
        assert "400" in msg
        assert "bad filter" in msg

    @responses.activate
    def test_error_body_truncated(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}notes",
            body="x" * 10000,
            status=400,
            content_type="text/plain",
        )

        with pytest.raises(WealthBoxAPIError) as exc_info:
            wb.api_post("notes", {})

        assert len(str(exc_info.value)) < 600


class TestNormalizeTags:
    """Write bodies want tags as ["a", "b"]; responses return [{id, name}].

    Shape confirmed at https://dev.wealthbox.com/ — create-note and
    create-contact request examples use "tags": ["Clients"], while the
    response schema documents tags as Array (Tag) objects.
    """

    def test_strings_pass_through(self):
        assert normalize_tags(["phone", "outbound"]) == ["phone", "outbound"]

    def test_response_shape_converted(self):
        assert normalize_tags([{"id": 1, "name": "phone"}]) == ["phone"]

    def test_mixed_shapes(self):
        assert normalize_tags(["a", {"id": 2, "name": "b"}]) == ["a", "b"]

    def test_empty(self):
        assert normalize_tags([]) == []

    @responses.activate
    def test_create_note_normalizes_object_tags_on_wire(self, wb):
        import json as json_mod
        responses.add(
            responses.POST,
            f"{BASE_URL}notes",
            json={"id": 1, "content": "hi"},
            status=201,
        )

        wb.create_note({
            "content": "hi",
            "linked_to": [{"id": 5, "type": "Contact"}],
            "tags": [{"id": 9, "name": "phone"}, "outbound"],
        })

        body = json_mod.loads(responses.calls[0].request.body)
        assert body["tags"] == ["phone", "outbound"]

    @responses.activate
    def test_create_contact_string_tags_unchanged_on_wire(self, wb):
        import json as json_mod
        responses.add(
            responses.POST,
            f"{BASE_URL}contacts",
            json={"id": 1},
            status=201,
        )

        wb.create_contact({"first_name": "A", "tags": ["Clients"]})

        body = json_mod.loads(responses.calls[0].request.body)
        assert body["tags"] == ["Clients"]

    @responses.activate
    def test_update_contact_normalizes_round_tripped_record(self, wb):
        import json as json_mod
        responses.add(
            responses.PUT,
            f"{BASE_URL}contacts/7",
            json={"id": 7},
            status=200,
        )

        # A record read from the API carries object-shaped tags; writing it
        # back must not 400
        wb.update_contact(7, {"first_name": "B", "tags": [{"id": 1, "name": "VIP"}]})

        body = json_mod.loads(responses.calls[0].request.body)
        assert body["tags"] == ["VIP"]

    @responses.activate
    def test_caller_dict_not_mutated(self, wb):
        responses.add(
            responses.POST,
            f"{BASE_URL}notes",
            json={"id": 1},
            status=201,
        )

        data = {"content": "hi", "tags": [{"id": 9, "name": "phone"}]}
        wb.create_note(data)

        assert data["tags"] == [{"id": 9, "name": "phone"}]


class TestTimeout:
    def test_default_timeout_passed_to_requests(self, wb, monkeypatch):
        captured = {}

        def fake_request(method, url, **kwargs):
            captured.update(kwargs)

            class FakeResponse:
                status_code = 200
                text = "{}"

                @staticmethod
                def json():
                    return {"id": 1}

            return FakeResponse()

        monkeypatch.setattr(wb._session, "request", fake_request)
        wb.api_get_single("contacts/1")

        assert captured["timeout"] == 30

    def test_custom_timeout(self, monkeypatch):
        wb = WealthBox(token="t", timeout=5)
        assert wb.timeout == 5

    def test_caller_params_not_mutated(self, wb):
        import responses as _responses
        with _responses.RequestsMock() as rsps:
            rsps.add(
                _responses.GET,
                f"{BASE_URL}contacts",
                json={"contacts": [], "meta": {"total_pages": 1}},
                status=200,
            )
            params = {"type": "Person"}
            wb.api_request("contacts", params=params)
            assert params == {"type": "Person"}


class TestCustomFieldsByName:
    CF_DEFS = {
        "custom_fields": [
            {"id": 501, "name": "Orion Household", "field_type": "text", "options": []},
            {"id": 502, "name": "Plan Type", "field_type": "single_select",
             "options": [{"label": "Will", "id": 9}, {"label": "Trust", "id": 10}]},
        ],
        "meta": {"total_pages": 1},
    }

    @responses.activate
    def test_update_contact_maps_name_to_id(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}categories/custom_fields",
            json=self.CF_DEFS, status=200,
        )
        responses.add(
            responses.PUT, f"{BASE_URL}contacts/7",
            json={"id": 7}, status=200,
        )

        wb.update_contact(7, {"first_name": "A"},
                          custom_fields={"Orion Household": "103"})

        import json as _j
        body = _j.loads(responses.calls[-1].request.body)
        assert body["custom_fields"] == [{"id": 501, "value": "103"}]
        assert body["first_name"] == "A"

    @responses.activate
    def test_unknown_field_name_raises(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}categories/custom_fields",
            json=self.CF_DEFS, status=200,
        )
        with pytest.raises(ValueError, match="No custom field named 'Nope'"):
            wb.build_custom_fields_payload("Contact", {"Nope": "x"})

    @responses.activate
    def test_single_select_unknown_option_raises(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}categories/custom_fields",
            json=self.CF_DEFS, status=200,
        )
        with pytest.raises(ValueError, match="not a valid option for 'Plan Type'"):
            wb.build_custom_fields_payload("Contact", {"Plan Type": "Guardian"})

    @responses.activate
    def test_single_select_valid_option(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}categories/custom_fields",
            json=self.CF_DEFS, status=200,
        )
        payload = wb.build_custom_fields_payload("Contact", {"Plan Type": "Trust"})
        assert payload == [{"id": 502, "value": "Trust"}]

    @responses.activate
    def test_defs_cached_across_calls(self, wb):
        responses.add(
            responses.GET, f"{BASE_URL}categories/custom_fields",
            json=self.CF_DEFS, status=200,
        )
        wb.build_custom_fields_payload("Contact", {"Orion Household": "1"})
        wb.build_custom_fields_payload("Contact", {"Orion Household": "2"})
        # definitions fetched once, then served from cache
        assert sum(1 for c in responses.calls if "custom_fields" in c.request.url) == 1

    def test_get_custom_field_value(self, wb):
        contact = {"custom_fields": [
            {"name": "Orion Household", "value": "103"},
            {"name": "Plan Type", "value": "Trust"},
        ]}
        assert wb.get_custom_field_value(contact, "orion household") == "103"
        assert wb.get_custom_field_value(contact, "Missing") is None
