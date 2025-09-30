# ai_engine/fraud_routes.py

from flask import Blueprint, request, jsonify
from ai_engine.fraud_detector import is_suspicious_transaction
from flask import Blueprint, jsonify
from finance.models import FraudLog

fraud_bp = Blueprint('fraud', __name__, url_prefix='/api/fraud')

@fraud_bp.route('/check', methods=['POST'])
def check_fraud():
    try:
        data = request.get_json()
        result = is_suspicious_transaction(data)

        return jsonify({
            "suspicious": result,
            "message": "Suspicious transaction" if result else "Transaction is clean"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ✅ Get all fraud logs
@fraud_bp.route('/logs', methods=['GET'])
def get_all_fraud_logs():
    logs = FraudLog.query.order_by(FraudLog.timestamp.desc()).all()
    return jsonify([log.to_dict() for log in logs]), 200

# ✅ Get fraud logs for a specific user
@fraud_bp.route('/logs/<int:user_id>', methods=['GET'])
def get_user_fraud_logs(user_id):
    logs = FraudLog.query.filter_by(user_id=user_id).order_by(FraudLog.timestamp.desc()).all()
    return jsonify([log.to_dict() for log in logs]), 200
