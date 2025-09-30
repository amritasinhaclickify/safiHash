from flask import Blueprint, request, jsonify
from savings.models import db, SavingsGroup, GroupMembership

savings_bp = Blueprint('savings', __name__, url_prefix='/api/savings')

# ✅ Create a savings group
@savings_bp.route('/group/create', methods=['POST'])
def create_group():
    data = request.get_json()
    name = data.get('name')
    user_id = data.get('user_id')

    if not name or not user_id:
        return jsonify({'error': 'Missing name or user_id'}), 400

    group = SavingsGroup(name=name, created_by=user_id)
    db.session.add(group)
    db.session.commit()

    membership = GroupMembership(group_id=group.id, user_id=user_id)
    db.session.add(membership)
    db.session.commit()

    return jsonify({'message': f'Group "{name}" created and joined successfully!'}), 201

# ✅ Join existing group
@savings_bp.route('/group/join', methods=['POST'])
def join_group():
    data = request.get_json()
    group_id = data.get('group_id')
    user_id = data.get('user_id')

    if not group_id or not user_id:
        return jsonify({'error': 'Missing group_id or user_id'}), 400

    exists = GroupMembership.query.filter_by(group_id=group_id, user_id=user_id).first()
    if exists:
        return jsonify({'message': 'Already a member'}), 200

    membership = GroupMembership(group_id=group_id, user_id=user_id)
    db.session.add(membership)
    db.session.commit()

    return jsonify({'message': 'Joined group successfully!'}), 201

# ✅ Get members of a group
@savings_bp.route('/group/<int:group_id>/members', methods=['GET'])
def group_members(group_id):
    members = GroupMembership.query.filter_by(group_id=group_id).all()
    result = [{'user_id': m.user_id, 'joined_at': m.joined_at.strftime("%Y-%m-%d")} for m in members]
    return jsonify(result), 200
