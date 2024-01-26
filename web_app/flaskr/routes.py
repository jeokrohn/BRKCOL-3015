import asyncio
import logging

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, session, render_template, url_for, redirect, current_app, request
from requests import Session
from wxc_sdk.as_api import AsWebexSimpleApi
from wxc_sdk.locations import Location
from wxc_sdk.people import Person
from wxc_sdk.person_settings.call_intercept import InterceptSetting
from wxc_sdk.rest import RestError
from wxc_sdk.telephony import NumberListPhoneNumber
from wxc_sdk.telephony.callqueue import CallQueue
from wxc_sdk.telephony.hg_and_cq import Agent

from .app_with_tokens import AppWithTokens

__all__ = ['oauth', 'core']

log = logging.getLogger(__name__)

oauth = OAuth()

# auto-configuration does not work b/c there is a mismatch between the issuer in the OID config and the iss claim in
# the JWT token obtained. Tracked in https://jira-eng-gpk2.cisco.com/jira/browse/SPARK-401218
# two options:
#   1) use auto-config and define claim_options when getting the JWT toke to override the issuer claim option
#      The registration is then as easy as:
#         webex = oauth.register('webex',
#                                server_metadata_url='https://webexapis.com/v1/.well-known/openid-configuration',
#                                client_kwargs={'scope': 'openid email profile phone address',
#                                               'code_challenge_method': 'S256',
#                                               })
#       .. but the claim_options have to be overridden b/c Wx returns an incompatible iss claim
#       token = webex.authorize_access_token(response_type='id_token',
#                                            claims_options={'iss': {'values': ['https://idbroker-b-us.webex.com/idb']}}
#                                            )
#
#   2) manually configure the client. Then an access token can be obtained w/o claim_options when getting the access
#   token. This minimizes the risk of the static reference to an issue host name. OTOH the iss claim is not validated.
#         webex = oauth.register('webex',
#                                access_token_url='https://webexapis.com/v1/access_token',
#                                authorize_url='https://webexapis.com/v1/authorize',
#                                jwks_uri='https://webexapis.com/v1/verification',
#                                client_kwargs={'scope': 'openid email profile phone address',
#                                               'code_challenge_method': 'S256',
#                                               })

# register Webex OIDC provider used for login via Webex
# documentation: https://developer.webex.com/docs/login-with-webex
# endpoint URLs are here: https://developer.webex.com/docs/login-with-webex#oauth-20-and-openid-connect-api-endpoints
webex = oauth.register('webex',
                       # server_metadata_url='https://webexapis.com/v1/.well-known/openid-configuration',
                       access_token_url='https://webexapis.com/v1/access_token',
                       authorize_url='https://webexapis.com/v1/authorize',
                       jwks_uri='https://webexapis.com/v1/verification',
                       client_kwargs={'scope': 'openid email profile phone address',
                                      'code_challenge_method': 'S256',
                                      })

core = Blueprint('core', __name__,
                 template_folder='templates',
                 static_folder='static')


@core.route('/')
def index():
    if not (user := session.get('user')):
        url = url_for('core.login')
        log.debug(f'"/": redirecting to {url}')
        response = redirect(url_for('core.login'))
        return response

    user: Person
    log.debug(f'"/": rendering index.html')
    return render_template('index.html',
                           title='BRKCOL-3015',
                           user=user)


@core.route('/login')
def login():
    log.debug(f'"/login": clearing user context')
    session.pop('user', None)
    log.debug(f'"/login": rendering index.html')
    return render_template('login.html',
                           title='BRKCOL-3015')


@core.route('/authenticate')
def authenticate():
    """
    Initiate OIDC PKCE auth flow
    """
    # redirect URL for /authorize endpoint
    # hardcoded localhost redirect URI to make sure that the redirection works with a Docker container. We can't have
    # Docker container local IP addresses in the redirect URI
    redirect_uri = request.url.replace('authenticate', 'authorize')
    # redirect_uri = url_for('core.authorize', _external=True)

    # initiate flow by redirecting client
    response = webex.authorize_redirect(redirect_uri, response_type='code')
    log.debug(f'"/authenticate": Initiate OIDC PKCE auth flow on "{request.url}", redirecting to '
              f'{response.headers["Location"]}')
    return response


@core.route('/authorize')
def authorize():
    """
    redirect URI for OIDC PKCE flow
    """
    log.debug(f'"/authorize": got code, getting id tokens')
    # get access tokens
    token = webex.authorize_access_token(response_type='id_token',
                                         # claims_options={'iss': {'values': ['https://idbroker-b-us.webex.com/idb']}}
                                         )
    # use access token to get actual user info
    log.debug(f'"/authorize": got id tokens, getting user info')
    with Session() as r_session:
        with r_session.get('https://webexapis.com/v1/userinfo',
                           headers={'Authorization': f'Bearer {token["access_token"]}'}) as r:
            r.raise_for_status()
            profile = r.json()
    log.debug(f'"/authorize": got user info: {profile}')

    # check whether the user exists
    ca: AppWithTokens = current_app
    email = profile['email']
    log.debug(f'"/authorize": verify that user "{email}" exists as calling user')
    user = next((user
                 for user in ca.api.people.list(email=email, calling_data=True)
                 if user.emails[0] == email and user.location_id is not None),
                None)
    if user is None:
        return render_template('login.html', error=f'user "{email}" not part of target org or not a calling user')

    # save user info to session ...
    session['user'] = user

    # ... and redirect to main page
    url = url_for('core.index')
    log.debug(f'"/authorize": successful login, redirecting to {url}')
    return redirect(url)


@core.route('/userinfo')
async def user_info():
    """
    Get info for current user
    """
    user = session.get('user')
    if not user:
        return ''
    user: Person
    ca: AppWithTokens = current_app
    async with AsWebexSimpleApi(tokens=ca.tokens) as api:
        # get location details and number for user
        log.debug(f'"/userinfo": getting location details and numbers')
        location, numbers = await asyncio.gather(
            api.locations.details(location_id=user.location_id),
            api.telephony.phone_numbers(owner_id=user.person_id)
        )
        location: Location
        numbers: list[NumberListPhoneNumber]
    numbers.sort(key=lambda n: n.phone_number_type, reverse=True)
    return dict(numbers=[n.dict() for n in numbers],
                location_name=location.name)


@core.route('/userphones')
def user_phones():
    """
    Get phones of current user
    """

    def mac_with_colons(mac: str) -> str:
        octets = (mac[i:i + 2] for i in range(0, len(mac), 2))
        return ':'.join(octets)

    user = session.get('user')
    if not user:
        return ''
    user: Person
    ca: AppWithTokens = current_app
    try:
        log.debug(f'"/userphones": getting user phones')
        devices = list(ca.api.devices.list(person_id=user.person_id))
    except RestError as e:
        log.error(f'"/userphones": getting user phones failed: {e}')
        return {'success': False,
                'message': f'{e}'}
    log.debug(f'"/userphones": returning device data')
    return {'success': True,
            'rows': [[device.product, mac_with_colons(device.mac), device.connection_status]
                     for device in devices
                     if device.product_type == 'phone']}


@core.route('/userqueues', methods=['POST', 'GET'])
async def user_queues():
    """
    Endpoint got the table of queues for a user
        * GET: get data to put into the table
            * queue name
            * location name
            * queue extension
            * tuple (enabled, location and queue id)
        * POST: update the joined state of the user in one queue
    """
    user = session.get('user')
    if not user:
        return ''
    user: Person
    ca: AppWithTokens = current_app
    if request.method == 'GET':
        async with AsWebexSimpleApi(tokens=ca.tokens) as api:
            # get all call queues
            log.debug(f'"/userqueues": getting list of call queues')
            queues = await api.telephony.callqueue.list()
            # get details for all call queues
            log.debug(f'"/userqueues": getting call queue details')
            details = await asyncio.gather(*[api.telephony.callqueue.details(location_id=queue.location_id,
                                                                             queue_id=queue.id)
                                             for queue in queues])
            details: list[CallQueue]
        # identify queues the user is agent in
        queues_with_user = [(queue, detail, agent)
                            for detail, queue in zip(details, queues)
                            if (agent := next((agent
                                               for agent in detail.agents
                                               if agent.agent_id == user.person_id),
                                              None))]
        queues_with_user: list[tuple[CallQueue, CallQueue, Agent]]
        log.debug(f'"/userqueues": returning user/queue information')
        return {'success': True,
                'rows': [[queue.name,
                          queue.location_name,
                          queue.extension,
                          (agent.join_enabled, f'{queue.location_id}.{queue.id}', detail.allow_agent_join_enabled)]
                         for queue, detail, agent in queues_with_user]}
    elif request.method == 'POST':
        """
        Update agent join state for one queue
        """
        joined = request.json.get('checked')
        location_id, queue_id = request.json.get('id').split('.')

        # get queue info and update queue
        log.debug(f'"/userqueues": getting call queue details')
        detail = ca.api.telephony.callqueue.details(location_id=location_id, queue_id=queue_id)
        # find agent to modify
        agent = next(ag for ag in detail.agents if ag.agent_id == user.person_id)
        # set the new join state
        agent.join_enabled = joined
        # update the queue
        log.debug(f'"/userqueues": updating call queue details for "{detail.name}"')
        ca.api.telephony.callqueue.update(location_id=location_id, queue_id=queue_id, update=detail)
        log.debug(f'"/userqueues": success')
        return {'success': True}


@core.route('/useroptions', methods=['POST', 'GET'])
async def user_options():
    """
    Endpoint to get/update user options
    For now only a single
    """
    user = session.get('user')
    if not user:
        return {'success': False}
    user: Person
    ca: AppWithTokens = current_app
    async with AsWebexSimpleApi(tokens=ca.tokens) as api:
        if request.method == 'GET':
            log.debug(f'"/useroptions": getting call intercept and call waiting status')
            call_intercept, call_waiting = await asyncio.gather(
                api.person_settings.call_intercept.read(person_id=user.person_id),
                api.person_settings.call_waiting.read(person_id=user.person_id))
            call_intercept: InterceptSetting
            call_waiting: bool
            log.debug(f'"/useroptions": returning intercept and call waiting status')
            return {'success': True,
                    'callIntercept': call_intercept.enabled,
                    'callWaiting': call_waiting}
        elif request.method == 'POST':
            checked = request.json.get('checked')
            checkbox_id = request.json.get('id')
            if checkbox_id == 'callIntercept':
                update = InterceptSetting(enabled=checked)
                log.debug(f'"/useroptions": updating call intercept: {checked}')
                await api.person_settings.call_intercept.configure(person_id=user.person_id, intercept=update)
            elif checkbox_id =='callWaiting':
                log.debug(f'"/useroptions": updating call waiting: {checked}')
                await api.person_settings.call_waiting.configure(person_id=user.person_id, enabled=checked)
            else:
                return {'success': False, 'message': f'unexpected checkbox id "{checkbox_id}"'}
            log.debug(f'"/useroptions": return success')
            return {'success': True}
    return {'success': False}


# This is required to avoid net::ERR_INVALID_HTTP_RESPONSE (304) when client
# requests the static/js resources from the flask app
@core.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store'
    return response
