from flask import Blueprint, jsonify
from security.models import AlertLog

security_bp = Blueprint('security', __name__, url_prefix='/api/security')

@security_bp.route('/alerts', methods=['GET'])
def get_alerts():
    alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).all()
    return jsonify([a.to_dict() for a in alerts]), 200
