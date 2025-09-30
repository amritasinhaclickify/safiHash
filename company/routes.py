# company/routes.py (सिर्फ ये दो handlers अपडेट करो)
import os
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from users.models import User, db
from finance.models import Wallet, TransactionHistory
from hedera_sdk.transfer import transfer_hbar

company_bp = Blueprint("company", __name__, url_prefix="/api/company")


# ✅ Get all employees (normal users)
@company_bp.route("/users", methods=["GET"])
@jwt_required()
def get_users_for_company():
    users = User.query.filter_by(role="user").all()
    return jsonify([{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "kyc_status": u.kyc_status,
        "hedera_account_id": u.hedera_account_id
    } for u in users]), 200


# ✅ Company Account Balance
@company_bp.route("/balance", methods=["GET"])
@jwt_required()
@jwt_required()
def get_company_balance():
    company_id = get_jwt_identity()
    wallet = Wallet.query.filter_by(user_id=company_id).first()
    return jsonify({"balance": wallet.balance if wallet else 0}), 200


# ✅ Company Transactions (fixed - no status field)
@company_bp.route("/transactions", methods=["GET"])
@jwt_required()
def company_transactions():
    company_id = int(get_jwt_identity())
    txs = TransactionHistory.query.filter_by(user_id=company_id, type="salary").order_by(TransactionHistory.id.desc()).all()
    # status हटाया, hedera fields जोड़े
    return jsonify([{
        "id": tx.id,
        "recipient_id": tx.recipient_id,
        "amount": tx.amount,
        "description": tx.description,
        "hedera_tx_id": tx.hedera_tx_id,
        "hedera_path": tx.hedera_path,
    } for tx in txs]), 200



# ✅ Pay Salaries to all employees (with Hedera trace)
@company_bp.route("/pay-salaries", methods=["POST"])
@jwt_required()
def pay_salaries():
    company_id = int(get_jwt_identity())
    company = User.query.get(company_id)
    company_wallet = Wallet.query.filter_by(user_id=company_id).first()

    if not company or company.role != "company":
        return jsonify({"error": "Forbidden: Only company can pay salaries"}), 403

    payload = request.get_json(silent=True) or {}
    salary_amount = float(payload.get("amount", 2000))

    employees = User.query.filter_by(role="user").all()
    total_required = salary_amount * len(employees)

    if not company_wallet or company_wallet.balance < total_required:
        return jsonify({"error": "Insufficient balance"}), 400

    # If company has no on-chain key saved, pay via operator (real transfer)
    payer_account = company.hedera_account_id or os.getenv("HEDERA_OPERATOR_ID")
    payer_key = getattr(company, "hedera_private_key", None) or os.getenv("HEDERA_OPERATOR_KEY")

    if not payer_account or not payer_key:
        return jsonify({"error": "No Hedera payer configured (account/key missing)."}), 400

    results = []
    for emp in employees:
        emp_wallet = Wallet.query.filter_by(user_id=emp.id).first()
        if not emp_wallet:
            # make sure everyone has a wallet
            emp_wallet = Wallet(user_id=emp.id, balance=0.0)
            db.session.add(emp_wallet)
            db.session.flush()

        if not emp.hedera_account_id:
            results.append({"employee": emp.username, "skipped": "No Hedera account linked"})
            continue

        # --- REAL Hedera transfer ---
        res = transfer_hbar(
            sender_account=payer_account,
            sender_key=payer_key,
            recipient_account=emp.hedera_account_id,
            amount_hbar=salary_amount,
        )

        # Local ledger update
        company_wallet.balance -= salary_amount
        emp_wallet.balance += salary_amount

        # Log transaction (with Hedera trace)
        tx = TransactionHistory(
            user_id=company_id,
            recipient_id=emp.id,
            type="salary",
            amount=salary_amount,
            description=f"Salary paid to {emp.username}",
            hedera_tx_id=res["transaction_id"],
            hedera_path=" → ".join(res["path"]),
        )
        db.session.add(tx)

        results.append({
            "employee": emp.username,
            "amount": salary_amount,
            "hedera_tx_id": res["transaction_id"],
            "path": res["path"],
            "status": res["status"],
        })

    db.session.commit()
    return jsonify({"message": "Salaries processed", "details": results}), 200
