from authlib.integrations.flask_client import OAuth
from flask import Blueprint, session, render_template, url_for, jsonify, redirect
from requests import Session

__all__ = ['oauth', 'webex', 'core']

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
@core.route('/index.html')
def index():
    if not session.get('profile'):
        return redirect(url_for('core.login'))

    return render_template('index.html',
                           title='BRKCOL-3015')


@core.route('/login.html')
def login():
    session.pop('profile', None)
    return render_template('login.html',
                           title='BRKCOL-3015')


@core.route('/authenticate')
def authenticate():
    """
    Initiate OIDC PKCE auth flow
    """
    # redirect URL for /authorize endpoint
    redirect_uri = url_for('core.authorize', _external=True)
    # initiate flow by redirecting client
    return webex.authorize_redirect(redirect_uri, response_type='code')


@core.route('/authorize')
def authorize():
    """
    redirect URI for OIDC PKCE flow
    """
    # get access tokens
    token = webex.authorize_access_token(response_type='id_token',
                                         # claims_options={'iss': {'values': ['https://idbroker-b-us.webex.com/idb']}}
                                         )
    # use access token to get actual user info
    with Session() as r_session:
        with r_session.get('https://webexapis.com/v1/userinfo',
                         headers={'Authorization': f'Bearer {token["access_token"]}'}) as r:
            r.raise_for_status()
            profile = r.json()

    # save user info to session ...
    session['profile'] = profile
    # ... and redirect to main page
    return redirect(url_for('core.index'))


# This is required to avoid net::ERR_INVALID_HTTP_RESPONSE (304) when client
# requests the static/js resources from the flask app
@core.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store'
    return response
