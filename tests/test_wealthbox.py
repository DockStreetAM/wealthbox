import datetime
import pytest
import responses
from wealthbox import WealthBox, WealthBoxAPIError, WealthBoxResponseError, WealthBoxRateLimitError


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
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 1}],
                "meta": {"total_pages": 3}
            },
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 2}],
                "meta": {"total_pages": 3}
            },
            status=200
        )
        responses.add(
            responses.GET,
            f"{BASE_URL}contacts",
            json={
                "contacts": [{"id": 3}],
                "meta": {"total_pages": 3}
            },
            status=200
        )

        result = wb.api_request("contacts")

        assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert len(responses.calls) == 3

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

        with pytest.raises(WealthBoxResponseError) as exc_info:
            wb.api_post("tasks", {"name": "New Task"})

        assert "Failed to decode JSON" in str(exc_info.value)


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

        assert "Delete failed" in str(exc_info.value)

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
    def test_update_workflow_step(self, wb):
        responses.add(
            responses.PUT,
            f"{BASE_URL}workflow_steps/123",
            json={"id": 123, "completed": True},
            status=200
        )

        result = wb.update_workflow_step(123, {"completed": True})

        assert result == {"id": 123, "completed": True}


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
