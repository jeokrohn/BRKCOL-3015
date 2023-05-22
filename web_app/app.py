#!/usr/bin/env python3
from dotenv import load_dotenv

from flaskr import create_app

if __name__ == "__main__":
    load_dotenv()
    app = create_app()
    app.run(host='127.0.0.1', debug=True, threaded=True)
