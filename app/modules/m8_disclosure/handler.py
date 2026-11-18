from flask import Blueprint
from app.web import api, page
bp = Blueprint('m8_disclosure', __name__)


@bp.get('/m8_disclosure')
def screen():
    return page(8, 'm8_disclosure.html')


@bp.route('/api/m8_disclosure', methods=['GET', 'POST'])
def preview():
    return api(8)
