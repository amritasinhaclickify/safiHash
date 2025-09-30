from flask import Blueprint, request, jsonify
from complaints.models import Complaint
from extensions import db

complaint_bp = Blueprint('complaints', __name__, url_prefix='/api/complaints')

# ✅ Submit complaint
@complaint_bp.route('/submit', methods=['POST'])
def submit_complaint():
    data = request.get_json()
    user_id = data.get('user_id')
    message = data.get('message')

    if not user_id or not message:
        return jsonify({"error": "Missing user_id or message"}), 400

    complaint = Complaint(user_id=user_id, message=message)
    db.session.add(complaint)
    db.session.commit()

    return jsonify({"message": "Complaint submitted successfully"}), 201

# ✅ View complaints (admin)
@complaint_bp.route('/all', methods=['GET'])
def view_all_complaints():
    complaints = Complaint.query.order_by(Complaint.timestamp.desc()).all()
    return jsonify([c.to_dict() for c in complaints]), 200
