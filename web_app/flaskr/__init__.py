from flask import Flask, jsonify
from flaskr.routes import core

app = Flask(__name__, static_folder=None)

app.config['TEMPLATES_AUTO_RELOAD'] = True

app.register_blueprint(core, url_prefix='/')


# This is required to avoid net::ERR_INVALID_HTTP_RESPONSE (304) when client
# requests the static/js resources from the flask app
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store'
    return response


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, threaded=True)
