from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from users.models import User
from finance.models import Wallet, TransactionHistory

ngo_bp = Blueprint("ngo", __name__, url_prefix="/api/ngo")

# ✅ Get all normal users (beneficiaries)
@ngo_bp.route("/users", methods=["GET"])
@jwt_required()
def get_users_for_ngo():
    users = User.query.filter_by(role="user").all()
    return jsonify([{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "kyc_status": u.kyc_status
    } for u in users]), 200

# ✅ NGO Account Balance
@ngo_bp.route("/balance", methods=["GET"])
@jwt_required()
@jwt_required()
def get_ngo_balance():
    ngo_id = get_jwt_identity()
    wallet = Wallet.query.filter_by(user_id=ngo_id).first()
    return jsonify({"balance": wallet.balance if wallet else 0}), 200

# ✅ NGO Transactions
@ngo_bp.route("/transactions", methods=["GET"])
@jwt_required()
def ngo_transactions():
    ngo_id = get_jwt_identity()
    txs = TransactionHistory.query.filter_by(user_id=ngo_id).all()
    return jsonify([{
        "id": tx.id,
        "recipient_id": tx.recipient_id,
        "amount": tx.amount,
        "status": tx.status,
        "description": tx.description
    } for tx in txs]), 200
