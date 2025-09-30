from flask import Blueprint, jsonify, request
from extensions import db
from users.models import User, KYCRequest
from finance.models import Loan, DepositRequest, TransactionHistory, Wallet
from hedera_sdk.kyc_service import set_kyc_status 
# Hedera imports
from hedera import Client, AccountId, PrivateKey, AccountBalanceQuery, Hbar, HbarUnit, TokenId
import os, traceback

bank_admin_bp = Blueprint('bank_admin', __name__, url_prefix='/api/bank-admin')

# ---------- 1. Get all users ----------
@bank_admin_bp.route('/users', methods=['GET'])
def get_all_users():
    users = User.query.all()
    return jsonify([{
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "hedera_id": user.hedera_account_id,
        "kyc_status": user.kyc_status,
        "role": user.role
    } for user in users]), 200


# ---------- 2. Get all loans ----------
@bank_admin_bp.route('/loans', methods=['GET'])
def get_all_loans():
    loans = Loan.query.all()
    return jsonify([{
        "id": loan.id,
        "user_id": loan.user_id,
        "amount": loan.amount,
        "purpose": loan.purpose,
        "status": loan.status
    } for loan in loans]), 200


# ---------- 3. Manually approve/reject loan ----------
@bank_admin_bp.route('/loans/<int:loan_id>/status', methods=['POST'])
def update_loan_status(loan_id):
    data = request.get_json()
    status = data.get('status')  # 'approved' or 'rejected'
    loan = Loan.query.get_or_404(loan_id)
    loan.status = status
    db.session.commit()
    return jsonify({"message": f"Loan {status} successfully."}), 200


# ---------- 4. Get all deposits ----------
@bank_admin_bp.route('/deposits', methods=['GET'])
def get_deposits():
    deposits = DepositRequest.query.all()
    return jsonify([{
        "id": d.id,
        "user_id": d.user_id,
        "amount": d.amount,
        "status": d.status
    } for d in deposits]), 200


# ---------- 5. Approve deposit ----------
@bank_admin_bp.route('/deposits/<int:deposit_id>/approve', methods=['POST'])
def approve_deposit(deposit_id):
    deposit = DepositRequest.query.get_or_404(deposit_id)

    if deposit.status != "pending":
        return jsonify({"error": "Already processed"}), 400

    deposit.status = "approved"
    wallet = Wallet.query.filter_by(user_id=deposit.user_id).first()
    if wallet:
        wallet.balance += deposit.amount
    else:
        wallet = Wallet(user_id=deposit.user_id, balance=deposit.amount)
        db.session.add(wallet)

    tx = TransactionHistory(
        user_id=deposit.user_id,
        type="deposit",
        amount=deposit.amount,
        description="Deposit approved by admin"
    )
    db.session.add(tx)
    db.session.commit()
    return jsonify({"message": f"Deposit of {deposit.amount} approved for user {deposit.user_id}"}), 200


# ---------- 6. Reject deposit ----------
@bank_admin_bp.route('/deposits/<int:deposit_id>/reject', methods=['POST'])
def reject_deposit(deposit_id):
    deposit = DepositRequest.query.get_or_404(deposit_id)

    if deposit.status != "pending":
        return jsonify({"error": "Already processed"}), 400

    deposit.status = "rejected"
    db.session.commit()
    return jsonify({"message": f"Deposit rejected for user {deposit.user_id}"}), 200


# ---------- 7. Get all KYC requests ----------
@bank_admin_bp.route('/kyc', methods=['GET'])
def get_all_kyc():
    requests = KYCRequest.query.all()
    return jsonify([{
        "id": req.id,
        "user_id": req.user_id,
        "document_type": req.document_type,
        "document_number": req.document_number,
        "status": req.status,
        "hedera_file_id": req.hedera_file_id,
        "hedera_file_hash": req.hedera_file_hash
    } for req in requests]), 200


# ---------- 8. Approve/Reject KYC ----------


@bank_admin_bp.route('/kyc/<int:request_id>/status', methods=['POST'])
def update_kyc_status(request_id):
    data = request.get_json()
    status = data.get('status')  # approved / rejected
    req = KYCRequest.query.get_or_404(request_id)

    # ✅ fetch user explicitly
    user = User.query.get(req.user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    req.status = status
    if status == "approved":
        user.kyc_status = "verified"
        set_kyc_status(user.id, True)   # ✅ Hedera update
    else:
        user.kyc_status = "unverified"
        set_kyc_status(user.id, False)  # ❌ Hedera revoke

    db.session.commit()
    return jsonify({"message": f"KYC {status} for user {req.user_id}"}), 200



# ---------- 9. Get Bank Account Balance (Hedera) — with token balances (incl. BHC) ----------
# Configure token id & decimals if you want to highlight BHC
BHC_TOKEN_ID_STR = os.getenv("BHC_TOKEN_ID", "0.0.6609133")
BHC_DECIMALS = int(os.getenv("BHC_DECIMALS", "2"))

@bank_admin_bp.route('/balance', methods=['GET'])
def get_bank_balance():
    try:
        operator_id_str = os.getenv("HEDERA_OPERATOR_ID")
        operator_key_str = os.getenv("HEDERA_OPERATOR_KEY")

        if not operator_id_str or not operator_key_str:
            return jsonify({"error": "Missing HEDERA_OPERATOR_ID or HEDERA_OPERATOR_KEY in .env"}), 500

        # ✅ build objects (Java-binding SDK style)
        try:
            operator_id = AccountId.fromString(operator_id_str)
            operator_key = PrivateKey.fromString(operator_key_str)
        except Exception:
            return jsonify({"error": "Invalid HEDERA_OPERATOR_ID or HEDERA_OPERATOR_KEY in .env"}), 500

        client = Client.forTestnet()
        client.setOperator(operator_id, operator_key)

        # ✅ query balance
        balance = AccountBalanceQuery().setAccountId(operator_id).execute(client)
        hbars_obj = balance.hbars

        # --- HBAR numeric conversion ---
        try:
            hbars_num = float(hbars_obj.to(HbarUnit.HBAR))
        except Exception:
            try:
                s = hbars_obj.toString()
                hbars_num = float(s.replace("ℏ", "").strip().split()[0])
            except Exception:
                hbars_num = None

        try:
            tinybars = int(hbars_obj.toTinybars())
        except Exception:
            tinybars = None

        balance_display = (
            f"{hbars_num:.8f} ℏ"
            if hbars_num is not None
            else (hbars_obj.toString() if hasattr(hbars_obj, "toString") else "unknown")
        )

        # --- Extract token balances robustly (Java map -> Python dict) ---
        tokens_raw = {}
        tokens_map = getattr(balance, "tokens", None)

        if tokens_map:
            parsed = False
            # Try dict-like .items()
            try:
                for k, v in tokens_map.items():
                    try:
                        tid = k.toString() if hasattr(k, "toString") else str(k)
                        amt = int(v.longValue()) if hasattr(v, "longValue") else int(v)
                        tokens_raw[tid] = amt
                    except Exception:
                        continue
                parsed = True
            except Exception:
                pass

            # Try Java entrySet() fallback if not parsed
            if not parsed:
                try:
                    entries = tokens_map.entrySet().toArray()
                    for e in entries:
                        try:
                            k = e.getKey()
                            v = e.getValue()
                            tid = k.toString() if hasattr(k, "toString") else str(k)
                            amt = int(v.longValue()) if hasattr(v, "longValue") else int(v)
                            tokens_raw[tid] = amt
                        except Exception:
                            continue
                except Exception:
                    tokens_raw = {}

        # --- Pretty token values (apply decimals if known) ---
        tokens_pretty = {}
        for tid, amt in tokens_raw.items():
            if amt is None:
                tokens_pretty[tid] = None
                continue
            try:
                if tid == BHC_TOKEN_ID_STR:
                    tokens_pretty[tid] = float(amt) / (10 ** BHC_DECIMALS)
                else:
                    tokens_pretty[tid] = float(amt)
            except Exception:
                tokens_pretty[tid] = float(amt) if amt is not None else None

        # --- Highlight BHC ---
        bhc_raw = tokens_raw.get(BHC_TOKEN_ID_STR)
        bhc_display = None
        if bhc_raw is not None:
            try:
                bhc_display = float(bhc_raw) / (10 ** BHC_DECIMALS)
            except Exception:
                bhc_display = float(bhc_raw)

        bhc_display_str = f"{bhc_display:,.2f} BHC" if bhc_display is not None else None

        return jsonify({
            "account_id": operator_id.toString(),
            "balance_hbar": hbars_num,
            "balance_tinybars": tinybars,
            "balance_display": balance_display,
            "tokens_raw": tokens_raw,
            "tokens_pretty": tokens_pretty,
            "bhc": {
                "token_id": BHC_TOKEN_ID_STR,
                "raw": bhc_raw,
                "decimals": BHC_DECIMALS,
                "display": bhc_display,
                "display_str": bhc_display_str
            }
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
