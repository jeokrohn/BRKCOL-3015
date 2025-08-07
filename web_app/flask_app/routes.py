import logging
from urllib.parse import urlparse

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, session, render_template, url_for, redirect, current_app, request
from requests import Session
from wxc_sdk.people import Person
from .app_with_tokens import AppWithTokens

__all__ = ['oauth', 'core']

TITLE = 'CLS-3215'

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


@core.before_request
def log_request():
    if request.is_json:
        log.debug(f'{request.method} {urlparse(request.url).path}: {request.get_json()}')


@core.after_request
def log_response(response):
    if response.is_json:
        log.debug(f'{request.method} {urlparse(request.url).path} {response.status}: {response.get_json()}')
    return response


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
                           title=TITLE,
                           user=user)


@core.route('/login')
def login():
    # clear user context
    log.debug(f'"/login": clearing user context')
    session.pop('user', None)
    log.debug(f'"/login": rendering index.html')
    return render_template('login.html',
                           title=TITLE)


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
        return render_template('login.html',
                               error=f'user "{email}" not part of target org or not a calling user')

    # save user info to session ...
    session['user'] = user

    # ... and redirect to main page
    url = url_for('core.index')
    log.debug(f'"/authorize": successful login, redirecting to {url}')
    return redirect(url)


# This is required to avoid net::ERR_INVALID_HTTP_RESPONSE (304) when client
# requests the static/js resources from the flask app
@core.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store'
    return response
