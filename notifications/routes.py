# notifications/routes.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from notifications.models import Notification

notifications_bp = Blueprint("notifications", __name__)

# -------- Get all notifications for logged-in user --------
@notifications_bp.route("/<int:user_id>", methods=["GET"])
@jwt_required()
@jwt_required()
def get_notifications(user_id):
    current_user = get_jwt_identity()
    if int(current_user) != user_id:
        return jsonify({"error": "Forbidden"}), 403

    notes = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).all()
    return jsonify([n.to_dict() for n in notes]), 200


# -------- Mark notification as read --------
@notifications_bp.route("/<int:note_id>/read", methods=["POST"])
@jwt_required()
def mark_as_read(note_id):
    note = Notification.query.get(note_id)
    if not note:
        return jsonify({"error": "Notification not found"}), 404

    current_user = get_jwt_identity()
    if note.user_id != int(current_user):
        return jsonify({"error": "Forbidden"}), 403

    note.is_read = True
    db.session.commit()
    return jsonify({"message": "Notification marked as read", "id": note.id}), 200


# -------- Create notification (system/internal use) --------
def create_notification(user_id, message, ntype="info", meta=None):
    note = Notification(user_id=user_id, message=message, type=ntype, meta=meta)
    db.session.add(note)
    db.session.commit()
    return note.to_dict()
