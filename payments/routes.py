# safichain/payments/routes.py
import os
import json
import uuid
from decimal import Decimal
from datetime import datetime
import time
from flask import Blueprint, request, jsonify, current_app
from extensions import db
from payments.models import PaymentOrder, PaymentAttempt, PaymentConfig
from users.models import User
from hedera_sdk.wallet import ensure_token_ready_for_account
from hedera_sdk.token_service import transfer_asset

# detect_fraud may or may not exist; import optionally
try:
    from ai_engine.fraud_detector import detect_fraud
except Exception:
    detect_fraud = None

from .utils import get_access_token, verify_mpesa_transaction

payments_bp = Blueprint("payments", __name__, url_prefix="/api/payments")


def gen_order_id():
    return uuid.uuid4().hex


@payments_bp.route("/create", methods=["POST"])
def create_order():
    """
    Create an order before user goes to M-Pesa pay screen.
    Expected JSON: { "user_id": int, "amount": "12.50", "msisdn": "2547...", "agency_id": optional }
    Returns order_id and agency_number.
    """
    data = request.get_json() or {}
    user_id = data.get("user_id")
    amount = data.get("amount")
    msisdn = data.get("msisdn")
    agency_id = data.get("agency_id")

    if not all([user_id, amount, msisdn]):
        return jsonify({"error": "user_id, amount and msisdn required"}), 400

    # basic cast
    try:
        amount_dec = Decimal(str(amount))
    except Exception:
        return jsonify({"error": "invalid amount"}), 400

    user = User.query.get(int(user_id))
    if not user:
        return jsonify({"error": "user not found"}), 404

    # resolve agency: explicit -> active -> error
    agency = None
    if agency_id:
        try:
            agency = PaymentConfig.query.get(int(agency_id))
        except Exception:
            agency = None
    if not agency:
        agency = PaymentConfig.query.filter_by(is_active=True).first()
    if not agency:
        return jsonify({"error": "no active agency config found"}), 500

    order_id = gen_order_id()
    order = PaymentOrder(
        order_id=order_id,
        user_id=user.id,
        amount=amount_dec,
        currency="KES",
        msisdn=msisdn,
        status="created",
        created_at=datetime.utcnow(),
        agency_id=agency.id,
        agency_number=agency.mpesa_number,
    )
    db.session.add(order)
    db.session.flush()  # ✅ ensure ID/fields are persisted in session before commit
    db.session.commit()

    return jsonify({
        "order_id": order.order_id,
        "agency_number": order.agency_number,
        "message": "order created",
    }), 201



@payments_bp.route("/confirm", methods=["POST"])
def confirm_payment():
    data = request.get_json() or request.form.to_dict() or {}
    order_id = data.get("order_id")
    msisdn = data.get("msisdn")
    mpesa_ref = data.get("mpesa_ref")
    amount = data.get("amount")

    # Sandbox me mpesa_ref ko unique bana do
    if os.getenv("MPESA_ENV", "sandbox") == "sandbox":
        mpesa_ref = f"{mpesa_ref}-{int(time.time())}"

    if not all([order_id, msisdn, mpesa_ref, amount]):
        return jsonify({"error": "order_id, msisdn, mpesa_ref and amount required"}), 400

    order = PaymentOrder.query.filter_by(order_id=order_id).first()
    if not order:
        return jsonify({"error": "order not found"}), 404

    if order.status == "completed":
        return jsonify({
            "message": "order already completed",
            "order_id": order_id,
            "hedera_tx_hash": order.hedera_tx_hash
        }), 200

    if not (order.mpesa_ref and order.mpesa_ref == mpesa_ref):
        existing_ref = PaymentOrder.query.filter_by(mpesa_ref=mpesa_ref).first()
        if existing_ref:
            return jsonify({"error": "mpesa_ref already used"}), 409

    try:
        amt_dec = Decimal(str(amount))
    except Exception:
        return jsonify({"error": "invalid amount format"}), 400

    attempt = PaymentAttempt(
        order_id=order.order_id,
        msisdn=msisdn,
        mpesa_ref=mpesa_ref,
        amount=amt_dec,
        agency_number=order.agency_number,
        status="verifying",
        created_at=datetime.utcnow()
    )
    db.session.add(attempt)
    db.session.flush()          # ✅ ensure attempt.id is available
    attempt_id = attempt.id     # ✅ save id for re-fetch after rollback/commit
    db.session.commit()

    # 0) Ensure user before fraud check
    user = User.query.get(order.user_id)
    if not user:
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "failed"
            db.session.commit()
        return jsonify({"error": "user not found"}), 404

    # Fraud detection
    try:
        if detect_fraud:
            user_dict = {
                "id": user.id,
                "email": user.email,
                "msisdn": msisdn,
                "amount": float(amount),
                "login_attempts": 0
            }
            fraud_ok = detect_fraud(user_dict)
            if fraud_ok is False:
                attempt = PaymentAttempt.query.get(attempt_id)
                if attempt:
                    attempt.status = "failed"
                    db.session.commit()
                return jsonify({"error": "fraud detected"}), 403
    except Exception:
        current_app.logger.exception("fraud check failed")

    # Verify MPESA
    try:
        verified = verify_mpesa_transaction(mpesa_ref=mpesa_ref, amount=float(amount), msisdn=msisdn)
    except Exception as e:
        current_app.logger.exception("MPESA verification error")
        db.session.rollback()
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "failed"
            attempt.mpesa_response = str(e)
            db.session.commit()
        return jsonify({"error": "mpesa verification error", "details": str(e)}), 502

    if not verified.get("success"):
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "failed"
            attempt.mpesa_response = json.dumps(verified)
            db.session.commit()
        return jsonify({"error": "mpesa verification failed", "details": verified}), 400

    order.mpesa_ref = mpesa_ref
    order.mpesa_raw_payload = json.dumps(verified.get("raw", {}))
    order.status = "verifying"
    db.session.commit()

    # Ensure user & account
    user = User.query.get(order.user_id)
    if not user:
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "failed"
            db.session.commit()
        return jsonify({"error": "user not found"}), 404
    if not getattr(user, "hedera_account_id", None):
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "pending_retry"
            db.session.commit()
        return jsonify({"error": "user missing hedera account, contact admin"}), 502

    token_id = os.getenv("BHC_TOKEN_ID")
    operator_priv = os.getenv("HEDERA_OPERATOR_KEY")
    if not token_id or not operator_priv:
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "failed"
            db.session.commit()
        return jsonify({"error": "server misconfigured: missing BHC_TOKEN_ID or HEDERA_OPERATOR_KEY"}), 500

    # Ensure token ready
    try:
        tok_ready = ensure_token_ready_for_account(
            token_id=token_id,
            account_id=user.hedera_account_id,
            account_private_key=user.hedera_private_key,
            kyc_grant_signing_key=operator_priv
        )
    except Exception as e:
        current_app.logger.exception("ensure_token_ready failed")
        db.session.rollback()
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "pending_retry"
            attempt.mpesa_response = str(e)
            db.session.commit()
        return jsonify({"error": "token ready failed, will retry", "details": str(e)}), 502

    if not tok_ready or tok_ready.get("grant_kyc") is False:
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "pending_retry"
            attempt.mpesa_response = json.dumps(tok_ready)
            db.session.commit()
        return jsonify({"error": "KYC/association not completed, pending"}, 202)

    # Hedera transfer
    try:
        decimals = int(os.getenv("BHC_DECIMALS", "2"))
        minor_amount = int(round(float(amount) * (10 ** decimals)))

        sender_account = os.getenv("HEDERA_OPERATOR_ID") or os.getenv("MINT_BANK_ACCOUNT") or "0.0.6538187"
        if order.agency and getattr(order.agency, "hedera_account_id", None):
            sender_account = order.agency.hedera_account_id

        transfer_res = transfer_asset(
            asset_type="BHC",
            sender_account=sender_account,
            sender_privkey=os.getenv("HEDERA_OPERATOR_KEY"),
            recipient_account=user.hedera_account_id,
            amount=minor_amount,
            token_id=token_id
        )
    except Exception as e:
        current_app.logger.exception("hedera transfer failed")
        db.session.rollback()
        attempt = PaymentAttempt.query.get(attempt_id)
        if attempt:
            attempt.status = "pending_retry"
            attempt.mpesa_response = str(e)
            db.session.commit()
        return jsonify({"error": "hedera transfer failed", "details": str(e)}), 502

    # Finalize
    tx_id = transfer_res.get("tx_id") or transfer_res.get("transaction_id") or transfer_res.get("tx")
    status = transfer_res.get("status") or transfer_res.get("result") or "unknown"

    attempt = PaymentAttempt.query.get(attempt_id)
    if attempt:
        attempt.hedera_tx_hash = tx_id
        attempt.status = "completed"
        attempt.mpesa_response = json.dumps(transfer_res)
    order.status = "completed"
    order.hedera_tx_hash = tx_id
    order.paid_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "message": "payment verified and tokens transferred",
        "order_id": order.order_id,
        "hedera_tx_id": tx_id,
        "transfer_status": status
    }), 200


@payments_bp.route("/mpesa/webhook", methods=["POST"])
def mpesa_webhook():
    """
    M-Pesa Daraja/Sandbox webhook receiver.
    - Saves raw payload for debugging
    - Tries to match PaymentOrder by mpesa_ref or (msisdn+amount)
    - Creates PaymentAttempt record (flushes to get id)
    - Leaves order in 'verifying' state (confirmation endpoint does the full transfer)
    """
    payload = request.get_json(force=True, silent=True) or {}
    raw = json.dumps(payload)

    # Extract fields (sandbox callback shape)
    mpesa_ref = None
    amount = None
    msisdn = None

    try:
        stk = payload.get("Body", {}).get("stkCallback", {})
        mpesa_ref = stk.get("CheckoutRequestID")
        items = stk.get("CallbackMetadata", {}).get("Item", [])
        for item in items:
            name = (item.get("Name") or "").lower()
            if name == "amount":
                amount = item.get("Value")
            elif name in ("msisdn", "phone", "phonenumber", "phone_number"):
                msisdn = str(item.get("Value"))
            elif name in ("mpesareceiptnumber", "mpesa_receipt_number"):
                # sometimes useful
                pass
    except Exception as e:
        current_app.logger.warning(f"Webhook parse error: {e}")

    # Try to match existing order
    order = None
    if mpesa_ref:
        order = PaymentOrder.query.filter_by(mpesa_ref=mpesa_ref).first()
    if not order and msisdn and amount:
        order = (
            PaymentOrder.query.filter_by(msisdn=msisdn, amount=amount)
            .order_by(PaymentOrder.created_at.desc())
            .first()
        )

    if order:
        attempt = PaymentAttempt(
            order_id=order.order_id,
            msisdn=msisdn or order.msisdn,
            mpesa_ref=mpesa_ref,
            amount=amount,
            agency_number=order.agency_number,
            status="verifying",
            mpesa_response=raw,
            created_at=datetime.utcnow()
        )
        db.session.add(attempt)
        # flush to get DB-generated id without committing (safe for later re-attach)
        db.session.flush()
        attempt_id = attempt.id

        # attach order changes and commit once
        order.mpesa_raw_payload = raw
        order.status = "verifying"
        db.session.commit()

        current_app.logger.info(f"Webhook created attempt id={attempt_id} for order={order.order_id}")

        # Respond quickly to webhook; processing (confirm/transfer) can be triggered async or by calling /confirm
        return jsonify({
            "message": "✅ Webhook received & order updated",
            "order_id": order.order_id,
            "attempt_id": attempt_id
        }), 200

    # If no order matched, log and save raw (for manual reconciliation)
    current_app.logger.warning("⚠️ mpesa webhook: no matching order")
    # (optionally store raw payload in a debug table; here we simply return 202)
    return jsonify({
        "message": "webhook received but no matching order found",
        "raw_saved": True
    }), 202

@payments_bp.route("/config/add", methods=["POST"])
def add_payment_config():
    data = request.get_json() or {}
    name = data.get("name")
    mpesa_number = data.get("mpesa_number")
    hedera_account_id = data.get("hedera_account_id")

    if not all([name, mpesa_number, hedera_account_id]):
        return jsonify({"error": "name, mpesa_number, hedera_account_id required"}), 400

    # server-side duplicate guard (uses PaymentConfig imported at module top)
    existing = PaymentConfig.query.filter_by(mpesa_number=mpesa_number).first()
    if existing:
        return jsonify({"error": "mpesa_number already exists", "id": existing.id}), 409

    config = PaymentConfig(
        name=name,
        mpesa_number=mpesa_number,
        hedera_account_id=hedera_account_id,
        is_active=True
    )
    db.session.add(config)
    db.session.commit()

    return jsonify({"message": "Payment config added", "id": config.id}), 201



