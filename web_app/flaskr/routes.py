import asyncio
import logging
from urllib.parse import urlparse

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, session, render_template, url_for, redirect, current_app, request
from requests import Session
from wxc_sdk.as_api import AsWebexSimpleApi
from wxc_sdk.people import Person
from wxc_sdk.rest import RestError
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

# register Webex OIDC provider
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
        log.debug(f'"/" redirecting to {url}')
        response = redirect(url_for('core.login'))
        return response

    user: Person
    return render_template('index.html',
                           title='BRKCOL-3015',
                           user_display=user.display_name,
                           user=user)


@core.route('/login')
def login():
    session.pop('user', None)
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
    log.debug(f'Initiate OIDC PKCE auth flow on "{request.url}", redirecting to {response.headers["Location"]}')
    return response


@core.route('/authorize')
def authorize():
    """
    redirect URI for OIDC PKCE flow
    """
    log.debug(f'/authorize: got code, getting id tokens')
    # get access tokens
    token = webex.authorize_access_token(response_type='id_token',
                                         # claims_options={'iss': {'values': ['https://idbroker-b-us.webex.com/idb']}}
                                         )
    # use access token to get actual user info
    log.debug(f'/authorize: got id tokens, getting user info')
    with Session() as r_session:
        with r_session.get('https://webexapis.com/v1/userinfo',
                           headers={'Authorization': f'Bearer {token["access_token"]}'}) as r:
            r.raise_for_status()
            profile = r.json()
    log.debug(f'/authorize: got user info: {profile}')

    # check whether the user exists
    ca: AppWithTokens = current_app
    email = profile['email']
    log.debug(f'/authorize: verify that user "{email}" exists')
    users = list(ca.api.people.list(email=email))
    if not users:
        return render_template('login.html', error=f'user "{email}" not part of target org')

    # save user info to session ...
    session['user'] = users[0]

    # ... and redirect to main page
    url = url_for('core.index')
    log.debug(f'/authorize: successful login, redirecting to {url}')
    return redirect(url)


@core.route('/userinfo')
def user_info():
    """
    Get info for current user
    """
    user = session.get('user')
    if not user:
        return ''
    user: Person
    ca: AppWithTokens = current_app
    log.debug(f'/userinfp: getting user details')
    user = ca.api.people.details(person_id=user.person_id, calling_data=True)
    if not user.location_id:
        return dict(numbers=[],
                    location_name='')
    log.debug(f'/userinfp: getting location details')
    location = ca.api.locations.details(location_id=user.location_id)
    log.debug(f'/userinfp: getting user\'s numbers')
    numbers = list(ca.api.telephony.phone_numbers(owner_id=user.person_id))
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
        devices = list(ca.api.devices.list(person_id=user.person_id))
    except RestError as e:
        return {'success': False,
                'message': f'{e}'}
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
        * POST: upadte the joined state of the user in one queue
    """
    user = session.get('user')
    if not user:
        return ''
    user: Person
    ca: AppWithTokens = current_app
    if request.method == 'GET':
        async with AsWebexSimpleApi(tokens=ca.tokens) as api:
            # get all call queues
            queues = await api.telephony.callqueue.list()
            # get details for all call queues
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
        detail = ca.api.telephony.callqueue.details(location_id=location_id, queue_id=queue_id)
        # find agent to modify
        agent = next(ag for ag in detail.agents if ag.agent_id == user.person_id)
        # set the new join state
        agent.join_enabled = joined
        # update the queue
        ca.api.telephony.callqueue.update(location_id=location_id, queue_id=queue_id, update=detail)
        return {'success': True}


# This is required to avoid net::ERR_INVALID_HTTP_RESPONSE (304) when client
# requests the static/js resources from the flask app
@core.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store'
    return response
