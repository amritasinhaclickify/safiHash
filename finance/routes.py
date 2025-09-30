# finance/routes.py
import os
from flask import Blueprint, request, jsonify
from finance.models import db, Loan, Wallet, Voting, TransactionHistory
from datetime import datetime
from finance.rewards import grant_reward, get_rewards, total_points
from finance.loan_logic import disburse_loan as core_disburse_loan  
from ai_engine.smart_contracts import disburse_loan
from ai_engine.fraud_detector import detect_fraud
from finance.models import FraudLog
from users.models import User
from hedera_sdk.transfer import transfer_hbar
from hedera_sdk.token_service import transfer_asset
from hedera import PrecheckStatusException, ReceiptStatusException
import traceback
import json
from ai_engine.smart_contracts import process_repayment as sc_process_repayment
from jnius import JavaException  # 👈 catch Hedera Java SDK errors cleanly


finance_bp = Blueprint('finance', __name__, url_prefix='/api/finance')
# ✅ money transfer
@finance_bp.route('/transfer', methods=['POST'])
def transfer_money():
    data = request.get_json() or {}
    sender_id     = data.get("sender_id")
    recipient_id  = data.get("recipient_id")
    asset_type    = (data.get("asset_type") or "").upper()  # force explicit

    # validate asset type
    if asset_type not in {"HBAR", "BHC"}:
        return jsonify({"error": "asset_type must be 'HBAR' or 'BHC'"}), 400

    # amount parse
    try:
        amount = float(data.get("amount", 0))
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400
    if not all([sender_id, recipient_id]) or amount <= 0:
        return jsonify({"error": "Missing fields or invalid amount"}), 400

    # load users
    sender = User.query.get(sender_id)
    recipient = User.query.get(recipient_id)
    if not sender or not recipient:
        return jsonify({"error": "Invalid sender or recipient"}), 404
    if not sender.hedera_account_id or not recipient.hedera_account_id:
        return jsonify({"error": "Hedera account missing for sender or recipient"}), 400

    # KYC guards (bank/super-admin bypass allowed)
    privileged = {"bank-admin", "super-admin"}
    if sender.role not in privileged and sender.kyc_status != "verified":
        return jsonify({"error": "Sender KYC not verified. Transfer blocked."}), 403
    if recipient.kyc_status != "verified":
        return jsonify({"error": "Recipient KYC not verified. Transfer blocked."}), 403

    # keys & token
    sender_key = os.getenv("HEDERA_OPERATOR_KEY")  # operator-funded until per-user keys available
    if not sender_key:
        return jsonify({"error": "HEDERA_OPERATOR_KEY not configured"}), 500

    token_id = None
    transfer_amount = amount
    if asset_type == "BHC":
        token_id = os.getenv("BHC_TOKEN_ID")
        if not token_id:
            return jsonify({"error": "BHC token not configured (BHC_TOKEN_ID missing)"}), 500
        # respect decimals=2
        decimals = 2
        minor_amount = int(round(amount * (10 ** decimals)))
        if minor_amount <= 0:
            return jsonify({"error": "Invalid BHC amount"}), 400
        transfer_amount = minor_amount  # send in minor units


    # ensure recipient is token-ready (for BHC only)
    if asset_type == "BHC":
        from hedera_sdk.wallet import ensure_token_ready_for_account
        token_id = os.getenv("BHC_TOKEN_ID")
        treasury_priv = os.getenv("HEDERA_OPERATOR_KEY")

        if token_id and treasury_priv and recipient.hedera_account_id and recipient.hedera_private_key:
            try:
                ensure_token_ready_for_account(
                    token_id=token_id,
                    account_id=recipient.hedera_account_id,
                    account_private_key=recipient.hedera_private_key,
                    kyc_grant_signing_key=treasury_priv,
                )
            except Exception as e:
                print(f"⚠️ Token-ready setup failed for recipient {recipient.id}: {e}")
    

    # perform transfer
    try:
        res = transfer_asset(
            asset_type=asset_type,
            sender_account=os.getenv("HEDERA_OPERATOR_ID"),
            sender_privkey=os.getenv("HEDERA_OPERATOR_KEY"),
            recipient_account=recipient.hedera_account_id,
            amount=transfer_amount,
            token_id=token_id
        )

    # normalize tx id
        tx_id = res.get("transaction_id") or res.get("tx_id") or ""

        txn = TransactionHistory(
            sender_id=sender.id,
            recipient_id=recipient.id,
            tx_type="transfer",
            asset_type=asset_type,
            token_id=token_id,
            amount=amount,  # store human-readable amount in DB
            description=f"{asset_type} transfer",
            from_account=os.getenv("HEDERA_OPERATOR_ID"),
            to_account=recipient.hedera_account_id,
            hedera_tx_id=tx_id,
            hedera_path=json.dumps([sender.hedera_account_id, recipient.hedera_account_id]),
            meta=json.dumps(res),
            timestamp=datetime.utcnow()
        )
        db.session.add(txn)
        db.session.commit()

        return jsonify({
           "message": f"✅ {amount} {asset_type} sent {sender.username} → {recipient.username} (tx_id: {tx_id})",
           "asset_type": asset_type,
           "token_id": token_id,
           "tx_id": tx_id
        }), 200


    except JavaException as je:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": "Hedera Java error", "details": str(je)}), 502
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"error": "Transfer failed", "details": str(e)}), 500

@finance_bp.route('/transactions', methods=['GET'])
def get_all_transaction_history():
    history = TransactionHistory.query.order_by(TransactionHistory.timestamp.desc()).all()
    results = []
    for t in history:
        try:
            path = json.loads(t.hedera_path) if t.hedera_path else []
        except Exception:
            path = []
        if not path:
            # fallback to 2-hop path if stored
            path = [t.from_account, t.to_account] if t.from_account and t.to_account else []

        results.append({
            "id": t.id,
            "sender_id": t.sender_id,
            "recipient_id": t.recipient_id,
            "type": t.tx_type,
            "asset_type": t.asset_type,  # 👈 no silent default
            "token_id": t.token_id,
            "amount": t.amount,
            "description": t.description,
            "from_account": t.from_account,
            "to_account": t.to_account,
            "tx_id": t.hedera_tx_id,
            "timestamp": t.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "path": path,
        })
    return jsonify(results), 200
# ---------- BHC helper admin endpoints (associate + KYC) ----------
@finance_bp.route('/bhc/setup-user', methods=['POST'])
def bhc_setup_user():
    """
    Body: { "user_id": 123 }
    User ko BHC token ke liye associate + KYC grant karta hai.
    Sirf Hedera se KYC confirm hone par hi DB status "verified" hoga.
    Retry loop bhi add kiya gaya hai (3 tries with backoff).
    """
    import time

    data = request.get_json() or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    token_id = os.getenv("BHC_TOKEN_ID")
    op_key   = os.getenv("HEDERA_OPERATOR_KEY")
    if not token_id:
        return jsonify({"error": "Missing BHC_TOKEN_ID in env"}), 500
    if not op_key:
        return jsonify({"error": "Missing HEDERA_OPERATOR_KEY in env"}), 500

    user = User.query.get(user_id)
    if not user or not user.hedera_account_id:
        return jsonify({"error": "User not found or Hedera account missing"}), 404

    # user's ED25519 private key required for association
    user_priv = getattr(user, "hedera_private_key", None)
    if not user_priv:
        user_priv = (data.get("account_privkey") or "").strip()
    if not user_priv:
        return jsonify({
            "error": "User private key not available",
            "hint": "Provide user's ED25519 private key in the request as 'account_privkey' or store it in users.hedera_private_key."
        }), 400

    from hedera_sdk.wallet import ensure_token_ready_for_account
    from jnius import JavaException

    out = {
        "user_id": user.id,
        "account": user.hedera_account_id,
        "token_id": token_id
    }

    tries = 3
    for attempt in range(1, tries + 1):
        try:
            ready = ensure_token_ready_for_account(
                token_id=token_id,
                account_id=user.hedera_account_id,
                account_private_key=user_priv,
                kyc_grant_signing_key=op_key
            )

            assoc = ready.get("associate")
            kyc   = ready.get("grant_kyc")

            out["associate"] = assoc
            out["kyc"] = kyc
            out["attempt"] = attempt

            if kyc is True:
                # ✅ success → mark verified
                user.kyc_status = "verified"
                db.session.commit()
                return jsonify({"message": f"BHC setup success (verified ✅) on attempt {attempt}", **out}), 200
            else:
                print(f"⚠️ Attempt {attempt}: KYC still pending, retrying...")
                time.sleep(attempt * 2)  # backoff

        except JavaException as je:
            msg = str(je)
            print(f"⚠️ JavaException during BHC setup (attempt {attempt}) for user {user_id}: {msg}")
            already_assoc = "TOKEN_ALREADY_ASSOCIATED_TO_ACCOUNT" in msg
            already_kyc   = "ACCOUNT_KYC_ALREADY_GRANTED_FOR_TOKEN" in msg
            if already_assoc or already_kyc:
                user.kyc_status = "verified"
                db.session.commit()
                out["note"] = "Already associated/KYC-granted"
                out["details"] = msg
                return jsonify({"message": "BHC already ready for this user", **out}), 200
            # otherwise wait and retry
            time.sleep(attempt * 2)

        except Exception as e:
            print(f"❌ Unexpected error attempt {attempt}: {e}")
            time.sleep(attempt * 2)

    # agar sab attempt fail ho gaye
    return jsonify({"error": "BHC setup failed after retries", **out}), 502


@finance_bp.route('/bhc/setup-verified', methods=['POST'])
def bhc_setup_all_verified():
    """
    Associates + grants KYC for ALL users with kyc_status == 'verified'.
    """
    token_id = os.getenv("BHC_TOKEN_ID")
    op_key = os.getenv("HEDERA_OPERATOR_KEY")
    if not token_id:
        return jsonify({"error": "Missing BHC_TOKEN_ID in env"}), 500
    if not op_key:
        return jsonify({"error": "Missing HEDERA_OPERATOR_KEY in env"}), 500

    from hedera_sdk.token_service import associate_token_with_account, grant_kyc

    users = User.query.filter(User.kyc_status == "verified").all()
    done, errors = [], []

    for u in users:
        if not u.hedera_account_id:
            errors.append({"user_id": u.id, "error": "no hedera_account_id"})
            continue
        try:
            a = associate_token_with_account(token_id, u.hedera_account_id, op_key)
            k = grant_kyc(token_id, u.hedera_account_id, op_key)
            done.append({"user_id": u.id, "account": u.hedera_account_id, "associate": a, "kyc": k})
        except Exception as e:
            errors.append({"user_id": u.id, "account": u.hedera_account_id, "error": str(e)})

    return jsonify({"processed": len(users), "success": done, "errors": errors}), 200
# -------------------------------------------------------------------
@finance_bp.route('/bhc/associate', methods=['POST'])
def bhc_associate_with_privkey():
    """
    DEV-ONLY: Associate a Hedera account with BHC using the *account's* private key,
    then grant KYC using operator key.

    Body:
    {
      "account_id": "0.0.xxxxxx",
      "account_privkey": "302e02... (ED25519)",
      "grant_kyc": true  # optional, default true
    }
    """
    data = request.get_json() or {}
    account_id = data.get("account_id")
    account_privkey = data.get("account_privkey")
    do_grant = data.get("grant_kyc", True)

    if not account_id or not account_privkey:
        return jsonify({"error": "account_id and account_privkey required"}), 400

    token_id = os.getenv("BHC_TOKEN_ID")
    op_key = os.getenv("HEDERA_OPERATOR_KEY")
    if not token_id:
        return jsonify({"error": "Missing BHC_TOKEN_ID in env"}), 500
    if not op_key:
        return jsonify({"error": "Missing HEDERA_OPERATOR_KEY in env"}), 500

    # Import inside to avoid circulars
    from hedera_sdk.token_service import associate_token_with_account, grant_kyc
    from jnius import JavaException

    out = {"account_id": account_id, "token_id": token_id}

    # 1) Associate (must be signed by the *account* key)
    try:
        a = associate_token_with_account(token_id, account_id, account_privkey)
        out["associate"] = a
    except JavaException as je:
        # Allow idempotency: already associated is fine
        msg = str(je)
        out["associate_error"] = msg
        if "TOKEN_ALREADY_ASSOCIATED_TO_ACCOUNT" not in msg:
            return jsonify({"error": "Associate failed", "details": msg}), 502

    # 2) KYC grant (signed by operator/treasury key, because you set KycKey to treasury pub)
    if do_grant:
        try:
            k = grant_kyc(token_id, account_id, op_key)
            out["kyc"] = k
        except JavaException as je:
            msg = str(je)
            out["kyc_error"] = msg
            if "ACCOUNT_KYC_ALREADY_GRANTED_FOR_TOKEN" not in msg:
                return jsonify({"error": "KYC grant failed", "details": msg}), 502

    return jsonify({"message": "Association/KYC processed", **out}), 200

    
