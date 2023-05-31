import os
from os.path import isdir, dirname, join, abspath

from dotenv import load_dotenv
from flask_session import Session

from .app_with_tokens import AppWithTokens

__all__ = ['create_app']


def create_app():
    # load .env from one level up
    env_path = abspath(join(dirname(__file__), '..', '.env'))
    load_dotenv(env_path)
    app = AppWithTokens(__name__, static_folder=None)

    app.config['TEMPLATES_AUTO_RELOAD'] = True

    # client id and secret for Webex OIDC client
    app.config['WEBEX_CLIENT_ID'] = os.getenv('CLIENT_ID')
    app.config['WEBEX_CLIENT_SECRET'] = os.getenv('CLIENT_SECRET')

    # session lifetime: 10 min
    app.config['PERMANENT_SESSION_LIFETIME'] = 600

    app.secret_key = os.urandom(50)
    app.config['SESSION_TYPE'] = 'filesystem'
    file_dir = 'sessions'
    file_dir = abspath(join(dirname(__file__), '..', file_dir))
    if not isdir(file_dir):
        os.mkdir(file_dir)
    app.config['SESSION_FILE_DIR'] = file_dir

    from .routes import core, oauth

    app.register_blueprint(core, url_prefix='/')
    sess = Session(app)
    sess.init_app(app)

    oauth.init_app(app)
    return app
