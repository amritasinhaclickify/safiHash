from flask import Blueprint, request, jsonify
from extensions import db
from users.models import User
from flask_jwt_extended import jwt_required, get_jwt_identity

super_admin_bp = Blueprint('super_admin', __name__, url_prefix='/api/super-admin')

# ✅ Get all users with roles
@super_admin_bp.route('/users', methods=['GET'])
@jwt_required()
@jwt_required()
def get_all_users():
    user_id = int(get_jwt_identity())
    super_admin = User.query.get(user_id)
    if not super_admin or super_admin.role != "super-admin":
        return jsonify({"error": "Forbidden"}), 403

    users = User.query.all()
    return jsonify([{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "kyc_status": u.kyc_status
    } for u in users]), 200


# ✅ Update user role
@super_admin_bp.route('/role/<int:user_id>', methods=['POST'])
@jwt_required()
def update_role(user_id):
    current_id = int(get_jwt_identity())
    super_admin = User.query.get(current_id)
    if not super_admin or super_admin.role != "super-admin":
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    new_role = data.get("role")

    if new_role not in ["user", "bank-admin", "ngo", "company", "super-admin"]:
        return jsonify({"error": "Invalid role"}), 400

    user = User.query.get_or_404(user_id)
    old_role = user.role
    user.role = new_role
    db.session.commit()

    return jsonify({
        "message": f"User {user.username} role changed from {old_role} to {new_role}"
    }), 200
