#!/usr/bin/env python3
import logging
import os

from flask_app import create_app

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger('urllib3').setLevel(logging.INFO)
    logging.getLogger('wxc_sdk.rest').setLevel(logging.INFO)
    app = create_app()
    if os.path.exists('/proc/1/cgroup'):
        # in Docker
        host = '0.0.0.0'
    else:
        host = '127.0.0.1'
    app.run(host=host, debug=True, threaded=True, port=5010)
