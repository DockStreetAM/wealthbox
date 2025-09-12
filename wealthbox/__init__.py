from json import JSONDecodeError
import requests
import datetime

import importlib.metadata
try:
    __version__ = importlib.metadata.version("wealthbox")  # your distribution name
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

class WealthBox(object):
    
    def __init__(self, token=None):
        self.token = token
        self.user_id = None
        self.base_url = f"https://api.crmworkspace.com/v1/"

    def raw_request(self,url_completion):
        url = self.base_url + url_completion
        res = requests.get(url,headers={'ACCESS_TOKEN': self.token})
        return res
    
    def api_request(self, endpoint, params=None, extract_key=None):
        url = self.base_url + endpoint
        page = 1
        total_pages = 9999999999
        if params is None:
            params = {}
        
        params.setdefault('per_page', '500')
        results = []

        extract_key = extract_key if extract_key is not None else endpoint

        while page <= total_pages:
            params['page'] = page
            res = requests.get(url,
                            params=params,
                            headers={'ACCESS_TOKEN': self.token})
            try:
                res_json = res.json()
                if 'meta' not in res_json:
                    total_pages = 1
                    results = res_json
                else:
                    total_pages = res_json['meta']['total_pages']
                    # The WB API usually (always?) returns a list of results under a key with the same name as the endpoint
                    try:
                        results.extend(res_json[extract_key.split('/')[-1]]) 
                    except KeyError:
                        print(f"Error: {res_json}")
                        return f"Error: {res.text}"
                page += 1
            except JSONDecodeError:
                return f"Error Decoding: {res.text}"

        return results
    
    def api_put(self, endpoint, data):
        url = self.base_url + endpoint
        res = requests.put(url,
                            json=data,
                            headers={'ACCESS_TOKEN': self.token})
        try:
            res_json = res.json()
        except JSONDecodeError:
            return f"Error Decoding: {res.text}"
        return res.json()

    def api_post(self, endpoint, data):
        url = self.base_url + endpoint
        res = requests.post(url,
                            json=data,
                            headers={'ACCESS_TOKEN': self.token})
        try:
            res_json = res.json()
        except JSONDecodeError:
            return f"Error Decoding: {res.text}"
        return res.json()
       
    def get_contacts(self, filters=None):
        return self.api_request('contacts',params=filters)

    def get_contact_by_name(self,name):
        return self.get_contacts({'name':name})

    def get_tasks(self, resource_id=None, resource_type=None, assigned_to=None, completed=None,other_filters=None):
        default_params = {
            'resource_type' : 'contact',
            'completed' : 'true',
            }

        called_params = {
            'resource_id': resource_id,
            'resource_type': resource_type,
            'assigned_to': assigned_to,
            'completed': completed if type(completed) =='bool' else None
            }
        other_filters = {} if other_filters is None else other_filters
        # Merge dicts and remove keys with None values
        called_params = {k: v for k, v in called_params.items() if v is not None}

        return self.api_request('tasks',params={**default_params, **called_params,**other_filters})
    
    def get_workflows(self, resource_id=None, resource_type=None, status=None):
        default_params = {
            'resource_type' : 'contact',
            'status' : 'active',
        }
        called_params = {
            'resource_id': resource_id,
            'resource_type': resource_type,
            'status': status,
        }
        # Merge dicts and remove keys with None values
        called_params = {k: v for k, v in called_params.items() if v is not None}
        
        p = {**default_params, **called_params}
        return self.api_request('workflows',params={**default_params, **called_params})
    
    def get_events(self, resource_id=None, resource_type='contact'):
        params = {}
        if resource_id:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        return self.api_request('events',params=params)
    
    def get_opportunities(self, resource_id=None, resource_type=None, order='asc', include_closed=True):
        params = {}
        if resource_id:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        if order:
            params['order'] = order
        if include_closed:
            params['include_closed'] = include_closed
        return self.api_request('opportunities',params=params)
    
    def get_notes(self, resource_id, resource_type="contact",order="asc"):
        params = {
            'resource_id' : resource_id,
            'resource_type' : resource_type
        }
        return self.api_request('notes',params=params, extract_key='status_updates')

    def get_categories(self,cat_type):
        return self.api_request(f'categories/{cat_type}')

    def get_tags(self, document_type=None):
        params = {}
        if document_type:
            params['document_type'] = document_type
        return self.api_request('categories/tags',params=params)
    
    def get_comments(self, resource_id, resource_type='status_update'):
        params = {}
        if resource_id:
            params['resource_id'] = resource_id
        if resource_type:
            params['resource_type'] = resource_type
        return self.api_request('comments',params=params)

    def get_my_user_id(self):
        #This endpoint doesn't have a 'meta'?
        self.user_id = self.api_request('me')['current_user']['id']
        return self.user_id

    def get_my_tasks(self):
        if self.user_id is None:
            self.get_my_user_id()
        return self.get_tasks({'assigned_to':self.user_id})

    def get_custom_fields(self,document_type=None):
        if document_type:
            params = {'document_type':document_type}
        else:
            params = None
        return self.api_request('categories/custom_fields',params=params)
    
    def update_contact(self,contact_id,updates_dict,custom_field=None):
        # Update a contact in WealthBox with a given ID and field data
        #TODO: Add custom field update
        return self.api_put(f'contacts/{contact_id}',updates_dict)

    def get_notes_with_comments(self,contact_id):
        notes = self.get_notes(contact_id)
        for note in notes:
            note['comments'] = self.get_comments(note['id'])
        return notes

    def get_events_with_comments(self,contact_id):
        events = self.get_events(contact_id)
        for event in events:
            event['comments'] = self.get_comments(event['id'], resource_type='event')
        return events

    def get_tasks_with_comments(self,contact_id):
        tasks = self.get_tasks(contact_id)
        for task in tasks:
            task['comments'] = self.get_comments(task['id'], resource_type='task')
        return tasks

    def get_workflows_with_comments(self,contact_id):
        # First get all workflows, completed, active and scheduled
        workflows = (
            self.get_workflows(contact_id, status='active') + 
            self.get_workflows(contact_id, status='completed') + 
            self.get_workflows(contact_id, status='scheduled'))
            
        for wf in workflows:
            for step in wf['workflow_steps']:
                step['comments'] = self.get_comments(step['id'], resource_type='WorkflowStep')
        return workflows

    def get_users(self):
        return self.api_request('users')

    def get_teams(self):
        return self.api_request('teams')
        
    def make_user_map(self,method="full"):
        user_list = self.get_users()
        if method == "full":
            user_dict = {user['id']:f'{user["id"]}; {user["name"]}; {user["email"]}' for user in user_list}
        elif method == "name":
            user_dict = {user['id']:user['name'] for user in user_list}
        elif method == "first_name":
            user_dict = {user['id']:user['name'].split(' ')[0] for user in user_list}
        elif method == "email":
            user_dict = {user['id']:user['email'] for user in user_list}
        else:
            raise Exception("method must be one of 'full', 'name', 'first_name', or 'email'")

        return user_dict

    def enhance_user_info(self,wb_data,method="full"):
        """ Walk through a stucture of data from the API (list of dicts, dict of dicts,etc)
        and replace the 'creator' field with information about the creator"""
        if type(method) == dict:
            user_map = method
        else:
            user_map = self.make_user_map(method)

        # if wb_data is not a dict or list, just return it
        if type(wb_data) not in [dict,list]:
            return wb_data
        if type(wb_data) == dict:
            if 'creator' in wb_data:
                wb_data['creator'] = user_map.get(wb_data['creator'],wb_data['creator']) 
            if 'assigned_to' in wb_data:
                wb_data['assigned_to'] = user_map.get(wb_data['assigned_to'],wb_data['assigned_to']) 
            return {k:self.enhance_user_info(v,user_map) for k,v in wb_data.items()}
        if type(wb_data) == list:
            return [self.enhance_user_info(d,user_map) for d in wb_data]

    def create_task_detailed(self,name,due_date=None,description=None,linked_to=None,
                             assigned_to=None,assigned_to_team=None,category=None,custom_fields=None):
        """custom_fields is a dict for setting any custom fields
           dict([Name of Field] : [Value])
           """
        if custom_fields is None:
            custom_fields = []
        if assigned_to is None:
            assigned_to = self.get_my_user_id()
        if linked_to is None:
            linked_to = []
        if due_date is None:
            due_date = datetime.date.today()
        # due date shoud be in JSON datetime format
        due_date = due_date.strftime('%Y-%m-%dT%H:%M:%SZ')

        data = {
            'name': name,
            'due_date': due_date,
            'linked_to': linked_to,
            'resource_type': 'contact',
            'description': description,
            'assigned_to': assigned_to,
            'custom_fields': custom_fields,
            'category': category,
        }
        return self.api_post('tasks',data)
    
    def create_task(self,title,due_date=None,description=None,
                    linked_to=None,assigned_to=None,category=None,**kwargs):
        """
        A more user friendly version to create a task
        kwargs can be used to capture any custom fields
        due: string or datetime. If string, should be WB later type "2 days later"
        linked_to: array of ids or a array of dicts
        assinged_to: string name of user or team
        """

        # Get all users and teams
        user_team_map = {}
        for user in self.get_users():
            # Insert full name and also first name and last
            user_team_map[user['name']] = user['id']
            user_team_map[user['name'].split(' ')[0]] = user['id']
            user_team_map[user['name'].split(' ')[-1]] = user['id']
        for team in self.get_teams():
            user_team_map[team['name']] = team['id']

        assigned_to_id = user_team_map.get(assigned_to,None)
        assigned_to_team = assigned_to in [team['name'] for team in self.get_teams()]

        if type(category) == str:
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
        if linked_to is not None:
            if type(linked_to) != list:
                linked_to = [linked_to]
            if len(linked_to) > 0:
                if type(linked_to[0]) == dict:
                    linked_to = [{'id':d['id'],'type':'Contact'} for d in linked_to]
                else:
                    linked_to = [{'id':id,'type':'Contact'} for id in linked_to]

        # Get the available custom fields for tasks
        custom_fields = self.get_custom_fields('Task')
        
        cf = {}
        for k,v in kwargs.items():
            # try to match kwargs to custom fields
            # no vetting of values is done
            # replace _ in k with space
            name = k.replace('_',' ')
            if name in [f['name'] for f in custom_fields]:
                cf[name] = v
                
        if assigned_to_team:
            return self.create_task_detailed(title,due_date,description=description,
                                         linked_to=linked_to,assigned_to_team=assigned_to_id,
                                         category=category_id,custom_fields=cf)
        else:
            return self.create_task_detailed(title,due_date,description=description,
                                         linked_to=linked_to,assigned_to=assigned_to_id,
                                         category=category_id,custom_fields=cf)