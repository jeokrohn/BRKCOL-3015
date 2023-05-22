from flask import render_template
from flask import Blueprint

core = Blueprint('core', __name__,
                 template_folder='templates',
                 static_folder='static')


@core.route('/')
@core.route('/index.html')
def index():
    return render_template('index.html',
                           title='BRKCOL-3015')


