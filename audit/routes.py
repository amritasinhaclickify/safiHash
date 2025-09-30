from flask import Blueprint, jsonify
from audit.models import AuditLog
from utils.audit_logger import log_audit_action

audit_bp = Blueprint('audit', __name__, url_prefix='/api/audit')

@audit_bp.route('/logs', methods=['GET'])
def get_all_logs():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return jsonify([log.to_dict() for log in logs]), 200



# Loan status
old_status = loan.status
loan.status = 'approved'
db.session.commit()

log_audit_action(
    user_id=user_id,
    action='Loan status update',
    table_name='Loan',
    record_id=loan.id,
    old={"status": old_status},
    new={"status": loan.status}
)
