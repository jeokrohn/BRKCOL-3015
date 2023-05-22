import base64
import os
from os.path import isdir, dirname, join, abspath

from dotenv import load_dotenv

__all__ = ['create_app', 'AppWithTokens']

from flask_session import Session

from .app_with_tokens import AppWithTokens


def create_app():
    # load .env from one level up
    env_pah = abspath(join(dirname(__file__), '..', '.env'))
    load_dotenv(env_pah)
    app = AppWithTokens(__name__, static_folder=None)

    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['WEBEX_CLIENT_ID'] = os.getenv('CLIENT_ID')
    app.config['WEBEX_CLIENT_SECRET'] = os.getenv('CLIENT_SECRET')

    app.secret_key = base64.b64decode(os.getenv('FLASK_SECRET_KEY'))
    app.config['SESSION_TYPE'] = 'filesystem'
    file_dir = os.getenv('FLASK_SESSION_FILE_DIR') or 'sessions'
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
