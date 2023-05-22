import base64
import os
from os.path import isdir

from flask import Flask

__all__ = ['create_app']

from flask_session import Session


def create_app():
    app = Flask(__name__, static_folder=None)

    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['WEBEX_CLIENT_ID'] = os.getenv('CLIENT_ID')
    app.config['WEBEX_CLIENT_SECRET'] = os.getenv('CLIENT_SECRET')

    app.secret_key = base64.b64decode(os.getenv('FLASK_SECRET_KEY'))
    app.config['SESSION_TYPE'] = 'filesystem'
    file_dir = os.getenv('FLASK_SESSION_FILE_DIR') or 'sessions'
    if not isdir(file_dir):
        os.mkdir(file_dir)
    app.config['SESSION_FILE_DIR'] = file_dir

    from .routes import core, oauth

    app.register_blueprint(core, url_prefix='/')
    sess = Session(app)
    sess.init_app(app)

    oauth.init_app(app)
    return app
