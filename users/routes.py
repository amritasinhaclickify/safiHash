from flask import Blueprint, request, jsonify, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    set_access_cookies, set_refresh_cookies,
    unset_jwt_cookies, jwt_required, get_jwt_identity
)
from users.models import db, User
from ai_engine.kyc_verifier import verify_document
from ai_engine.fraud_detector import detect_fraud
from finance.models import FraudLog
from notifications.models import Notification
import json
# Hedera + Logging
from hedera_sdk.wallet import create_hedera_account                    # ✅ correct
from utils.audit_logger import log_audit_action
from utils.consensus_helper import publish_to_consensus
from finance.models import DepositRequest 
from utils.trust_utils import calculate_trust_score

users_bp = Blueprint('users', __name__, url_prefix='/api/users')

@users_bp.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not username or not email or not password:
        return jsonify({'error': 'Missing required fields'}), 400

    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({'error': 'User already exists'}), 409

    # 1) Create user shell (to get DB id)
    new_user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        hedera_account_id=None,
        hedera_private_key=None,
        kyc_status="unverified"
    )
    db.session.add(new_user)
    db.session.commit()  # new_user.id available

    # 2) Create Hedera account, MUST have id + private key
    try:
        acct = create_hedera_account(user_id=new_user.id, metadata={"source": "register"})
        if not acct or not acct.get("account_id") or not acct.get("private_key"):
            db.session.delete(new_user)   # cleanup if Hedera failed
            db.session.commit()
            return jsonify({'error': 'Hedera account creation failed'}), 502

        new_user.hedera_account_id  = acct["account_id"]
        new_user.hedera_private_key = acct["private_key"]
        db.session.commit()

    except Exception as e:
        try:
            db.session.delete(new_user)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'error': f'Hedera account creation failed: {str(e)}'}), 500

    # 3) Publish + audit (non-blocking)
    try:
        publish_to_consensus({"event": "onboard", "user_id": new_user.id, "account": new_user.hedera_account_id})
    except Exception:
        pass

    try:
        log_audit_action(
            user_id=new_user.id,
            action="Onboard Hedera (register)",
            table_name="User",
            record_id=new_user.id,
            old={},
            new={"hedera_account_id": new_user.hedera_account_id}
        )
    except Exception:
        pass

    return jsonify({
        'message': 'User registered successfully',
        'hedera_account_id': new_user.hedera_account_id
    }), 201



# ✅ Login Route with Hedera auto-create if missing
@users_bp.route('/login', methods=['POST'])
def login_user():
    data = request.get_json()
    username_or_email = data.get('username')
    password = data.get('password')

    if not username_or_email or not password:
        return jsonify({'error': 'Missing credentials'}), 400

    user = User.query.filter(
        (User.username == username_or_email) | (User.email == username_or_email)
    ).first()

    if user and check_password_hash(user.password_hash, password):

        # ✅ If Hedera account missing (backfill)
        if not user.hedera_account_id or not user.hedera_private_key:
            try:
                acct = create_hedera_account(user_id=user.id, metadata={"source": "login"})
                if not acct or not acct.get("account_id") or not acct.get("private_key"):
                    return jsonify({'error': 'Hedera account creation failed (no key returned)'}), 502

                user.hedera_account_id  = acct["account_id"]
                user.hedera_private_key = acct["private_key"]
                db.session.commit()

                # Audit + consensus
                try:
                    log_audit_action(
                        user_id=user.id,
                        action="Onboard Hedera (auto-login)",
                        table_name="User",
                        record_id=user.id,
                        old={},
                        new={"hedera_account_id": user.hedera_account_id}
                    )
                except Exception:
                    pass
                try:
                    publish_to_consensus({"event": "onboard", "user_id": user.id, "account": user.hedera_account_id})
                except Exception:
                    pass

            except Exception as e:
                db.session.rollback()
                return jsonify({'error': f'Hedera account creation failed: {str(e)}'}), 500

        # ✅ Normal JWT issue
        access_token = create_access_token(identity=str(user.id))
        refresh_token = create_refresh_token(identity=str(user.id))

        resp = jsonify({
            'message': 'Login successful',
            'id': user.id,
            'username': user.username,
            'hedera_account_id': user.hedera_account_id,
            'kyc_status': user.kyc_status,
            'role': getattr(user, "role", "user"),
            'access_token': access_token
        })
        set_access_cookies(resp, access_token)
        set_refresh_cookies(resp, refresh_token)
        return resp, 200

    return jsonify({'error': 'Invalid credentials'}), 401



# ✅ Logout Route
@users_bp.route('/logout', methods=['POST'])
def logout_user():
    resp = jsonify({"message": "Logout successful"})
    unset_jwt_cookies(resp)
    return resp, 200


# ✅ Protected user info route
@users_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "kyc_status": user.kyc_status,
        "hedera_id": user.hedera_account_id
        
    })


# ✅ KYC Verification Route (Now supports auto/manual)
@users_bp.route('/kyc/<int:user_id>', methods=['POST'])
def kyc_verification(user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # ✅ Prevent duplicate KYC submissions
        if user.kyc_status in ["pending", "verified"]:
            return jsonify({
                "message": f"KYC already {user.kyc_status}.",
                "status": user.kyc_status
            }), 400

        data = request.get_json()
        result = verify_document(data)

        if result["status"] == "failed":
            return jsonify(result), 400

        # ✅ Check system config for mode
        from users.models import get_config
        mode = (get_config("kyc_mode", "manual") or "manual").lower()

        # Default values
        req_status = "pending"
        user_status = "pending"

        if mode == "auto":
            req_status = "approved"
            user_status = "verified"

        # ✅ Update user KYC status
        user.kyc_status = user_status

        # ✅ Save KYC request in a separate table
        from finance.models import KYCRequest
        req = KYCRequest(
            user_id=user.id,
            document_type="National ID",                 # required field
            document_number=data.get("national_id"),     # required field
            raw_data=json.dumps(data),
            status=req_status
        )
        db.session.add(req)
        db.session.commit()

        return jsonify({
            "message": f"KYC {'auto-approved' if mode=='auto' else 'submitted successfully. Awaiting admin approval.'}",
            "status": req_status
        }), 201

    except Exception as e:
        return jsonify({
            "error": "Error in KYC processing",
            "details": str(e)
        }), 500



# ✅ Notifications Route
@users_bp.route('/notifications/<int:user_id>', methods=['GET'])
def get_notifications(user_id):
    notifications = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).all()
    return jsonify([n.to_dict() for n in notifications])


# ✅ Trust Score Route
@users_bp.route('/trust-score/<int:user_id>/<int:group_id>', methods=['GET'])
def get_trust_score(user_id, group_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    result = calculate_trust_score(user_id=user_id, group_id=group_id, window_days=7)
    return jsonify({
        "user_id": user_id,
        "group_id": group_id,
        "trust_score": result["overall"],
        "params": result["params"]
    }), 200


# ✅ Fraud Check Route
@users_bp.route('/fraud-check/<int:user_id>', methods=['GET'])
def fraud_check(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user_data = {
        "kyc_verified": (user.kyc_status == "verified"),
        "loan_defaults": 4,
        "login_attempts": 6
    }

    result = detect_fraud(user_data)

    if result["is_fraud"]:
        log = FraudLog(user_id=user_id, alerts=", ".join(result["alerts"]))
        db.session.add(log)
        db.session.commit()

    return jsonify(result), 200


# ✅ Auth page
@users_bp.route("/auth", methods=["GET"])
def auth_page():
    return render_template("auth.html")

# ✅ Deposit Request Route
@users_bp.route('/deposit', methods=['POST'])
@jwt_required()
def deposit_request():
    user_id = int(get_jwt_identity())
    data = request.json
    amount = data.get("amount")
    note = data.get("note")

    if not amount or amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400

    req = DepositRequest(user_id=user_id, amount=amount, note=note)
    db.session.add(req)
    db.session.commit()

    return jsonify({"message": "Deposit request submitted. Waiting for admin approval."}), 201

# Add these endpoints somewhere in users/routes.py (e.g. after /me)

@users_bp.route('/<int:user_id>/kyc/status', methods=['GET'])
@jwt_required()
def get_user_kyc_status(user_id):
    """
    Return kyc_status + hedara proof (file_id + hash) for a user.
    Accessible only if requester is admin or requesting their own record.
    """
    try:
        requester_raw = get_jwt_identity()
        try:
            requester_id = int(requester_raw)
        except Exception:
            requester_id = requester_raw

        requester = User.query.get(requester_id)
        if not requester:
            return jsonify({"error": "Requester not found"}), 404

        # allow if admin or owner
        if requester.role != "admin" and requester.id != user_id:
            return jsonify({"error": "Forbidden"}), 403

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "user_id": user.id,
            "kyc_status": user.kyc_status,
            "kyc_file_id": user.kyc_file_id,
            "kyc_file_hash": user.kyc_file_hash
        }), 200

    except Exception as e:
        return jsonify({"error": "Error fetching KYC status", "details": str(e)}), 500


@users_bp.route('/me/kyc/status', methods=['GET'])
@jwt_required()
def get_my_kyc_status():
    """Helper for frontend: current user KYC status"""
    try:
        raw_id = get_jwt_identity()
        try:
            user_id = int(raw_id)
        except Exception:
            user_id = raw_id

        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "user_id": user.id,
            "kyc_status": user.kyc_status,
            "kyc_file_id": user.kyc_file_id,
            "kyc_file_hash": user.kyc_file_hash
        }), 200

    except Exception as e:
        return jsonify({"error": "Error fetching KYC status", "details": str(e)}), 500
