from __future__ import annotations

from json import JSONDecodeError
from typing import Any
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


class WealthBox:

    def __init__(
        self,
        token: str | None = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5
    ) -> None:
        self.token = token
        self.user_id: int | None = None
        self.base_url = "https://api.crmworkspace.com/v1/"

        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "PUT", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)

        self._session = requests.Session()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update({'ACCESS_TOKEN': self.token})

    def _check_rate_limit(self, response: requests.Response) -> None:
        """Check if response indicates rate limiting and raise if so."""
        if response.status_code == 429:
            retry_after = response.headers.get('Retry-After')
            retry_seconds = int(retry_after) if retry_after else None
            raise WealthBoxRateLimitError(
                "Rate limit exceeded",
                retry_after=retry_seconds
            )

    def raw_request(self, url_completion: str) -> requests.Response:
        url = self.base_url + url_completion
        res = self._session.get(url)
        self._check_rate_limit(res)
        return res
    
    def api_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        extract_key: str | None = None
    ) -> list[dict[str, Any]] | dict[str, Any]:
        url = self.base_url + endpoint
        page = 1
        total_pages = 9999999999
        if params is None:
            params = {}

        params.setdefault('per_page', '500')
        results: list[dict[str, Any]] = []

        extract_key = extract_key if extract_key is not None else endpoint

        while page <= total_pages:
            params['page'] = page
            res = self._session.get(url, params=params)
            self._check_rate_limit(res)
            try:
                res_json = res.json()
                if 'meta' not in res_json:
                    total_pages = 1
                    results = res_json
                else:
                    total_pages = res_json['meta']['total_pages']
                    # The WB API usually (always?) returns a list of results under a key with the same name as the endpoint
                    key = extract_key.split('/')[-1]
                    if key not in res_json:
                        raise WealthBoxAPIError(
                            f"Expected key '{key}' not found in response",
                            response=res_json
                        )
                    results.extend(res_json[key])
                page += 1
            except JSONDecodeError as e:
                raise WealthBoxResponseError(
                    f"Failed to decode JSON response: {e}",
                    response_text=res.text
                )

        return results

    def api_put(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url + endpoint
        res = self._session.put(url, json=data)
        self._check_rate_limit(res)
        try:
            res_json = res.json()
        except JSONDecodeError as e:
            raise WealthBoxResponseError(
                f"Failed to decode JSON response: {e}",
                response_text=res.text
            )
        return res_json

    def api_post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url + endpoint
        res = self._session.post(url, json=data)
        self._check_rate_limit(res)
        try:
            res_json = res.json()
        except JSONDecodeError as e:
            raise WealthBoxResponseError(
                f"Failed to decode JSON response: {e}",
                response_text=res.text
            )
        return res_json
       
    def get_contacts(
        self, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return self.api_request('contacts', params=filters)

    def get_contact_by_name(self, name: str) -> list[dict[str, Any]]:
        return self.get_contacts({'name': name})

    def get_tasks(
        self,
        resource_id: int | None = None,
        resource_type: str | None = None,
        assigned_to: int | None = None,
        completed: bool | str | None = None,
        other_filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
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

    def get_workflows(
        self,
        resource_id: int | None = None,
        resource_type: str | None = None,
        status: str | None = None
    ) -> list[dict[str, Any]]:
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

        return self.api_request('workflows', params={**default_params, **called_params})

    def get_events(
        self,
        resource_id: int | None = None,
        resource_type: str = 'contact'
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if resource_id:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        return self.api_request('events', params=params)

    def get_opportunities(
        self,
        resource_id: int | None = None,
        resource_type: str | None = None,
        order: str = 'asc',
        include_closed: bool = True
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if resource_id:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        if order:
            params['order'] = order
        if include_closed:
            params['include_closed'] = include_closed
        return self.api_request('opportunities', params=params)

    def get_notes(
        self,
        resource_id: int,
        resource_type: str = "contact",
        order: str = "asc"
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            'resource_id': resource_id,
            'resource_type': resource_type
        }
        return self.api_request('notes', params=params, extract_key='status_updates')

    def get_categories(self, cat_type: str) -> list[dict[str, Any]]:
        return self.api_request(f'categories/{cat_type}')

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

    def get_my_user_id(self) -> int:
        # This endpoint doesn't have a 'meta'?
        self.user_id = self.api_request('me')['current_user']['id']
        return self.user_id

    def get_my_tasks(self) -> list[dict[str, Any]]:
        if self.user_id is None:
            self.get_my_user_id()
        return self.get_tasks({'assigned_to': self.user_id})

    def get_custom_fields(
        self, document_type: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, str] | None = None
        if document_type:
            params = {'document_type': document_type}
        return self.api_request('categories/custom_fields', params=params)

    def update_contact(
        self,
        contact_id: int,
        updates_dict: dict[str, Any],
        custom_field: Any = None
    ) -> dict[str, Any]:
        # TODO: Add custom field update
        return self.api_put(f'contacts/{contact_id}', updates_dict)

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
            if 'creator' in wb_data:
                wb_data['creator'] = user_map.get(wb_data['creator'], wb_data['creator'])
            if 'assigned_to' in wb_data:
                wb_data['assigned_to'] = user_map.get(wb_data['assigned_to'], wb_data['assigned_to'])
            return {k: self.enhance_user_info(v, user_map) for k, v in wb_data.items()}
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
        for team in self.get_teams():
            user_team_map[team['name']] = team['id']

        assigned_to_id = user_team_map.get(assigned_to) if assigned_to else None
        is_team = assigned_to in [team['name'] for team in self.get_teams()] if assigned_to else False

        category_id: int | None
        if isinstance(category, str):
            task_categories = self.get_categories('task_categories')
            category_id = [c['id'] for c in task_categories if c['name'] == category][0]
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