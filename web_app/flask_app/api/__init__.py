import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from urllib.parse import urlparse

from flask import session, current_app, Blueprint, request
from flask_restx import Api, Resource, fields
from werkzeug.exceptions import UnsupportedMediaType
from wxc_sdk.devices import ProductType
from wxc_sdk.locations import Location
from wxc_sdk.people import Person
from wxc_sdk.person_settings.call_intercept import InterceptSetting
from wxc_sdk.rest import RestError
from wxc_sdk.telephony import NumberListPhoneNumber
from wxc_sdk.telephony.callqueue import CallQueue
from wxc_sdk.telephony.callqueue.agents import CallQueueAgentQueue
from wxc_sdk.telephony.hg_and_cq import Agent
from ..app_with_tokens import AppWithTokens

__all__ = ["apib"]

log = logging.getLogger(__name__)

apib = Blueprint('api', __name__, url_prefix='/api')

api = Api(apib,
          title='Frontend API',
          version='1.0',
          description='API for user frontend',
          doc='/docs',
          default='Frontend API',
          default_label='Frontend API')


@apib.before_request
def before_request():
    """
    Before request handler to log all requests
    """
    log.debug(f'Request: {request.method} {request.url}')
    if request.args:
        log.debug(f'Request: Query parameters: {request.args}')
    try:
        json_data = request.get_json()
    except UnsupportedMediaType:
        json_data = None
    if json_data is not None:
        log.debug(f'Request: JSON payload: {json_data}')


def assert_user(func):
    """
    Decorator to assert that a user is logged in.
    If not, return a 401 Unauthorized.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        user = session.get('user')
        if not user:
            return {'error': 'User not logged in'}, 401
        return func(*args, **kwargs)

    return wrapper


@api.route('/userinfo')
class UserInfo(Resource):
    """
    Endpoint to get user information.
    """

    @staticmethod
    @assert_user
    def get():
        """
        Get user information including location details and phone numbers for the logged-in user.
        Returns a JSON object with:
            * numbers: List of phone numbers associated with the user, each represented as a JSON object
            * location_name: Name of the user's location
        """
        user = session.get('user')
        user: Person
        ca: AppWithTokens = current_app
        capi = ca.api
        # get location details and number for user
        log.debug(f'"/api/userinfo": getting location details and numbers')
        tasks = [
            lambda: capi.locations.details(location_id=user.location_id),
            lambda: list(capi.telephony.phone_numbers(owner_id=user.person_id))
        ]
        with ThreadPoolExecutor(max_workers=10) as executor:
            location, numbers = list(executor.map(lambda f: f(), tasks))
        location: Location
        numbers: list[NumberListPhoneNumber]

        # noinspection PyUnboundLocalVariable
        numbers.sort(key=lambda n: n.phone_number_type, reverse=True)
        # noinspection PyUnboundLocalVariable
        return dict(numbers=[n.model_dump(mode='json') for n in numbers],
                    location_name=location.name), 200


@api.route('/userphones')
class UserPhones(Resource):
    """
    Get phones of current user
    """

    @staticmethod
    @assert_user
    def get():
        """
        Get phones of current user.
        Returns a JSON object with:
            * success: True if the operation was successful
            * rows: List of phone data rows. Each row in the table will contain:
                * product: Product name of the phone
                * mac: MAC address of the phone in colon-separated format
                * connection_status: Connection status of the phone
        """

        def mac_with_colons(mac: str) -> str:
            octets = (mac[i:i + 2] for i in range(0, len(mac), 2))
            return ':'.join(octets)

        user = session.get('user')
        user: Person
        ca: AppWithTokens = current_app
        path = urlparse(request.url).path
        try:
            log.debug(f'"{path}": getting user phones')
            devices = list(ca.api.devices.list(person_id=user.person_id))
        except RestError as e:
            log.error(f'"{path}": getting user phones failed: {e}')
            return {'success': False,
                    'message': f'{e}'}
        log.debug(f'"{path}": returning device data')
        return {'success': True,
                'rows': [{'model': device.product,
                          'mac': mac_with_colons(device.mac),
                          'status': device.connection_status}
                         for device in devices
                         if device.product_type == ProductType.phone]}


@api.route('/userqueues')
class UserQueues(Resource):
    """
    Endpoint to get data for the table of queues for a user
        * GET: get data to put into the table
            * queue name
            * location name
            * queue extension
            * tuple (enabled, location and queue id)
        * POST: update the joined state of the user in one queue
    """

    @staticmethod
    @assert_user
    def get():
        """
        Get data for the table of queues for a user.

        Response has:
        * success: True if the operation was successful
        * rows: List of queue data rows. Each row in the table will contain:
            * name: queue name
            * location: location name
            * extension: queue extension
            * join_info:
                * joined: True if the user is joined to the queue, False otherwise
                * location_and_queue_id: location and queue id is in format "location_id.queue_id"
                * allow_join_enabled: True if the user can join the queue
        """
        user = session.get('user')
        user: Person

        def get_agent_queues(agent_id: str, has_cx_essentials: bool) -> list[CallQueueAgentQueue]:
            """
            get list of queues the user is agent of and catch 404 errors
            :param agent_id: ID of the agent to get queues for
            :param has_cx_essentials: True if the agent has CX essentials, False otherwise
            :return: list of CallQueueAgentQueue objects
            """
            try:
                detail = ca_api.telephony.callqueue.agents.details(id=agent_id, has_cx_essentials=has_cx_essentials,
                                                                   max_=50)
                return detail.queues
            except RestError as e:
                if e.response.status_code == 404:
                    return []
                raise

        # get the current app
        ca: AppWithTokens = current_app
        ca_api = ca.api

        # get the path for logging
        path = urlparse(request.url).path

        # get agent details w/ and w/o CX essentials
        log.debug(f'"{path}": getting agent details with and without CX essentials')
        tasks = [
            lambda: get_agent_queues(agent_id=user.person_id, has_cx_essentials=False),
            lambda: get_agent_queues(agent_id=user.person_id, has_cx_essentials=True)]
        with ThreadPoolExecutor(max_workers=10) as executor:
            agent_queues, agent_queues_with_cx_essentials = list(executor.map(lambda f: f(), tasks))
        agent_queues: list[CallQueueAgentQueue]
        # noinspection PyUnboundLocalVariable
        agent_queues.extend(agent_queues_with_cx_essentials)

        # get details for the call queues the user is agent of
        log.debug(f'"{path}": getting call queue details for {len(agent_queues)} queues the user is agent of')
        tasks = [partial(ca_api.telephony.callqueue.details, location_id=agent_queue.location_id,
                         queue_id=agent_queue.id)
                 for agent_queue in agent_queues]
        details = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            # run the tasks in parallel
            details = list(executor.map(lambda f: f(), tasks))
        details: list[CallQueue]

        queues_with_user = [(queue, detail, agent)
                            for detail, queue in zip(details, agent_queues)
                            if (agent := next((agent
                                               for agent in detail.agents
                                               if agent.agent_id == user.person_id),
                                              None))]
        queues_with_user: list[tuple[CallQueueAgentQueue, CallQueue, Agent]]
        log.debug(f'"{path}": returning user/queue information')
        # each row in the table will contain:
        #   * name: queue name
        #   * location: location name
        #   * extension: queue extension
        #   * join_info:
        #       * joined: True if the user is joined to the queue, False otherwise
        #       * location_and_queue_id: location and queue id is in format "location_id.queue_id"
        #       * allow_join_enabled: True if the user can join the queue
        return {'success': True,
                'rows': [{'name': queue.name,
                          'location': queue.location_name,
                          'extension': queue.extension,
                          'join_info': {'joined': agent.join_enabled,
                                        'location_and_queue_id': f'{queue.location_id}.{queue.id}',
                                        'allow_join_enabled': detail.allow_agent_join_enabled}}
                         for queue, detail, agent in queues_with_user]}

    # parameter type for the POST request
    # to update the user join state in a queue
    PostUserQueues = api.model('PostUserQueues', {
        'id': fields.String(required=True, description='Location and queue id in format "location_id.queue_id"'),
        'checked': fields.Boolean(required=True,
                                  description='True if the user should be joined to the queue, False otherwise')
    })

    @staticmethod
    @api.expect(PostUserQueues, validate=True)
    @assert_user
    def post():
        """
        Update agent join state for one queue.
        """
        user = session.get('user')
        user: Person

        # get the current app
        ca: AppWithTokens = current_app
        ca_api = ca.api

        # get the path for logging
        path = urlparse(request.url).path

        # get parameters from the validated payload
        location_id, queue_id = api.payload['id'].split('.')
        joined = api.payload['checked']

        # get queue info and update queue
        log.debug(f'"{path}": getting call queue details')
        detail = ca_api.telephony.callqueue.details(location_id=location_id, queue_id=queue_id)

        # find agent to modify
        agent = next(ag for ag in detail.agents if ag.agent_id == user.person_id)

        # set the new join state
        agent.join_enabled = joined

        # update the queue
        log.debug(f'"{path}": updating call queue details for "{detail.name}"')
        ca_api.telephony.callqueue.update(location_id=location_id, queue_id=queue_id, update=detail)
        log.debug(f'"{path}": success')
        return {'success': True}


@api.route('/useroptions')
class UserOptions(Resource):
    """
    Endpoint to get/update user options (call intercept and call waiting).
    * GET: get user options
        * callIntercept: True if call intercept is enabled, False otherwise
        * callWaiting: True if call waiting is enabled, False otherwise
    * POST: update user options
        * id: 'callIntercept' or 'callWaiting'
        * checked: True if the option is enabled, False otherwise
    """

    @staticmethod
    @assert_user
    def get():
        """
        Get user options (call intercept and call waiting).
        Returns a JSON object with:
            * success: True if the operation was successful
            * callIntercept: True if call intercept is enabled, False otherwise
            * callWaiting: True if call waiting is enabled, False otherwise
        """
        user = session.get('user')
        # if not user:
        #     return {'error': 'User not logged in'}, 401
        user: Person
        ca: AppWithTokens = current_app
        capi = ca.api
        path = urlparse(request.url).path
        log.debug(f'"{path} getting call intercept and call waiting status')
        tasks = [
            lambda: capi.person_settings.call_intercept.read(entity_id=user.person_id),
            lambda: capi.person_settings.call_waiting.read(entity_id=user.person_id)
        ]
        with ThreadPoolExecutor(max_workers=10) as executor:
            call_intercept, call_waiting = list(executor.map(lambda f: f(), tasks))
        call_intercept: InterceptSetting
        call_waiting: bool
        log.debug(f'"{path}": returning intercept and call waiting status')
        # noinspection PyUnboundLocalVariable
        return {'success': True,
                'callIntercept': call_intercept.enabled,
                'callWaiting': call_waiting}

    PostUserOptions = api.model('PostUserOptions', {
        'id': fields.String(required=True, description='callIntercept or callWaiting'),
        'checked': fields.Boolean(required=True, description='True if option is enabled, False otherwise')})

    @api.expect(PostUserOptions, validate=True)
    @assert_user
    def post(self):
        """
        Update user options (call intercept and call waiting).
        Expects a JSON payload with:
            * id: 'callIntercept' or 'callWaiting'
            * checked: True if the option should be enabled, False otherwise
        Returns a JSON object with:
            * success: True if the operation was successful, False otherwise
            * message: error message if the operation failed
        """
        user = session.get('user')
        user: Person
        ca: AppWithTokens = current_app
        capi = ca.api
        path = urlparse(request.url).path
        checked = api.payload['checked']
        checkbox_id = api.payload['id']
        if checkbox_id == 'callIntercept':
            update = InterceptSetting(enabled=checked)
            log.debug(f'"{path}": updating call intercept: {checked}')
            capi.person_settings.call_intercept.configure(entity_id=user.person_id, intercept=update)
        elif checkbox_id == 'callWaiting':
            log.debug(f'"{path}": updating call waiting: {checked}')
            capi.person_settings.call_waiting.configure(entity_id=user.person_id, enabled=checked)
        else:
            return {'success': False, 'message': f'unexpected checkbox id "{checkbox_id}"'}
        log.debug(f'"{path}": return success')
        return {'success': True}
