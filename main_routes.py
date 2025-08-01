from flask import Blueprint, render_template

main_bp = Blueprint('main_bp', __name__)

@main_bp.route('/ayuda')
def ayuda():
    return render_template('ayuda.html')


