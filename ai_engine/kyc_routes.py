# ai_engine/kyc_routes.py
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import traceback
import os
import hashlib
from users.models import User, KYCRequest, db, get_config, set_config
from ai_engine.kyc_verifier import verify_document

# Use standardized consensus helper
from utils.consensus_helper import publish_to_consensus as consensus_publish
from utils.audit_logger import log_audit_action

# --- Upload config (safe defaults; can be overridden from app.config) ---
UPLOAD_FOLDER = os.getenv("KYC_UPLOAD_FOLDER", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXT = set(os.getenv("KYC_ALLOWED_EXT", "png,jpg,jpeg,pdf").split(","))
MAX_FILE_BYTES = int(os.getenv("KYC_MAX_BYTES", str(5 * 1024 * 1024)))  # default 5MB

kyc_bp = Blueprint('kyc', __name__, url_prefix="/api/kyc")



def _is_allowed_filename(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXT


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

@kyc_bp.route('/submit', methods=['POST'])
@jwt_required()
def submit_kyc():
    try:
        data = request.get_json()
        current_user_id = get_jwt_identity()
        if not data:
            return jsonify({"error": "No KYC data provided"}), 400

        # Validate KYC document
        kyc_result = verify_document(data)
        if kyc_result["status"] == "failed":
            return jsonify({
                "message": "KYC validation failed",
                "errors": kyc_result["errors"]
            }), 400

        # Check KYC mode (auto/manual)
        mode = (get_config("kyc_mode", "manual") or "manual").lower()
        initial_status = "approved" if mode == "auto" else "pending"

        # Normalize keys for DB
        doc_number = (
            data.get("national_id")
            or data.get("document_number")
            or data.get("id_no")
        )

        new_req = KYCRequest(
            user_id=current_user_id,
            document_type=data.get("document_type", "National ID"),
            document_number=doc_number,
            raw_data=str(data),
            status=initial_status,
            submitted_at=datetime.utcnow()
        )

        try:
            db.session.add(new_req)

            # If AUTO mode → mark user verified immediately
            if mode == "auto":
                user = User.query.get(current_user_id)
                if user:
                    user.kyc_status = "verified"
                try:
                    new_req.raw_data = (new_req.raw_data or "") + "\nauto_approved:True"
                except Exception:
                    pass
                new_req.status = "approved"

            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            return jsonify({
                "error": "DB error saving KYC request",
                "details": str(db_err)
            }), 500

        # Audit + consensus
        try:
            if mode == "auto":
                payload = {
                    "action": "KYC_AUTO_APPROVE",
                    "user_id": current_user_id,
                    "req_id": new_req.id,
                    "status": "approved"
                }
                log_audit_action(
                    user_id=current_user_id,
                    action="KYC_AUTO_APPROVE",
                    table_name="KYCRequest",
                    record_id=new_req.id,
                    old={},
                    new=payload
                )
                consensus_publish(payload)
                return jsonify({
                    "message": "KYC auto-approved",
                    "status": "approved",
                    "req_id": new_req.id
                }), 201
            else:
                payload = {
                    "action": "KYC_SUBMIT",
                    "user_id": current_user_id,
                    "req_id": new_req.id,
                    "status": "pending"
                }
                log_audit_action(
                    user_id=current_user_id,
                    action="KYC_SUBMIT",
                    table_name="KYCRequest",
                    record_id=new_req.id,
                    old={},
                    new=data
                )
                consensus_publish(payload)
        except Exception:
            traceback.print_exc()

        # Manual case ka final response
        return jsonify({
            "message": "KYC submitted successfully",
            "status": "pending",
            "req_id": new_req.id
        }), 201

    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({
            "error": "Error submitting KYC",
            "details": str(e),
            "traceback": tb
        }), 500


@kyc_bp.route('/toggle_mode', methods=['POST'])
@jwt_required()
def toggle_mode():
    # authenticated user (assumed admin in your workflow) toggles persistent mode
    cur = (get_config("kyc_mode", "manual") or "manual").lower()
    new_mode = "auto" if cur != "auto" else "manual"
    set_config("kyc_mode", new_mode)
    return jsonify({"message": f"KYC mode switched to {new_mode.upper()}", "mode": new_mode}), 200

@kyc_bp.route('/mode', methods=['GET'])
@jwt_required()
def get_mode():
    mode = (get_config("kyc_mode", "manual") or "manual").lower()
    return jsonify({"mode": mode}), 200


@kyc_bp.route('/approve/<int:req_id>', methods=['POST'])
@jwt_required()
def approve_kyc(req_id):
    try:
        current_user_id = get_jwt_identity()
        # If AUTO mode is enabled, skip admin check and approve directly
        kyc_mode = (get_config("kyc_mode", "manual") or "manual").lower()
        if kyc_mode == "auto":
            admin = User(id=0, role="system")  # fake system user
        else:
            admin = User.query.get(current_user_id)
            if not admin or admin.role != "admin":
                return jsonify({"error": "Admin privileges required"}), 403

        kyc_req = KYCRequest.query.get(req_id)
        if not kyc_req:
            return jsonify({"error": "KYC request not found"}), 404

        if kyc_req.status == "approved":
            return jsonify({"message": "Already approved", "req_id": req_id}), 200

        # Attempt to mint NFT (best-effort). Keep metadata minimal and non-sensitive.
        nft_result = None
        try:
            # lazy import fallback handled earlier in original file context
            from hedera_sdk.nft import mint_nft  # may raise; that's okay
            metadata = f"kyc-verified:user:{kyc_req.user_id}:req:{kyc_req.id}".encode("utf-8")
            nft_result = mint_nft(metadata)
        except Exception as e:
            nft_result = {"status": "error", "error": str(e)}

        # Update DB atomically: KYCRequest + User.kyc_status
        try:
            user = User.query.get(kyc_req.user_id)
            kyc_req.status = "approved"
            if user:
                user.kyc_status = "verified"
            try:
                kyc_req.raw_data = (kyc_req.raw_data or "") + f"\n nft:{str(nft_result)}"
            except Exception:
                pass

            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            return jsonify({"error": "DB error during approval", "details": str(db_err)}), 500
        # ------------------ NEW: make Hedera token-ready (associate + grant KYC) ------------------
        try:
            # read config from Flask app config or environment (ensure these are set)
            token_id = current_app.config.get("BHC_TOKEN_ID") or os.getenv("BHC_TOKEN_ID")
            treasury_priv = current_app.config.get("TREASURY_PRIVATE_KEY") or os.getenv("TREASURY_PRIVATE_KEY")

            # only attempt if we have required values and user has Hedera account + key
            if token_id and treasury_priv and user and user.hedera_account_id and user.hedera_private_key:
                from hedera_sdk.wallet import ensure_token_ready_for_account

                token_setup = ensure_token_ready_for_account(
                    token_id=token_id,
                    account_id=user.hedera_account_id,
                    account_private_key=user.hedera_private_key,
                    kyc_grant_signing_key=treasury_priv,
                )
                # log result but do not fail the whole approval if token setup partially fails
                current_app.logger.info(f"Token setup for user {user.id}: {token_setup}")
        except Exception as e:
            # best-effort only: record warning but continue
            current_app.logger.warning(f"Token setup failed for user {kyc_req.user_id}: {e}")

        # Publish to Hedera consensus and audit
        try:
            payload = {
                "action": "KYC_APPROVE",
                "user_id": kyc_req.user_id,
                "req_id": req_id,
                "status": "approved",
                "nft": nft_result
            }
            log_audit_action(user_id=current_user_id, action="KYC_APPROVE", table_name="KYCRequest",
                             record_id=req_id, old={}, new=payload)
            consensus_publish(payload)
        except Exception:
            traceback.print_exc()

        return jsonify({"message": "KYC approved", "req_id": req_id, "nft": nft_result}), 200

    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({"error": "Error approving KYC", "details": str(e), "traceback": tb}), 500


@kyc_bp.route('/reject/<int:req_id>', methods=['POST'])
@jwt_required()
def reject_kyc(req_id):
    try:
        current_user_id = get_jwt_identity()
        admin = User.query.get(current_user_id)
        if not admin or admin.role != "admin":
            return jsonify({"error": "Admin privileges required"}), 403

        kyc_req = KYCRequest.query.get(req_id)
        if not kyc_req:
            return jsonify({"error": "KYC request not found"}), 404

        if kyc_req.status == "rejected":
            return jsonify({"message": "Already rejected", "req_id": req_id}), 200

        try:
            kyc_req.status = "rejected"
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            return jsonify({"error": "DB error during rejection", "details": str(db_err)}), 500

        # Audit + consensus
        try:
            payload = {"action": "KYC_REJECT", "user_id": kyc_req.user_id, "req_id": req_id, "status": "rejected"}
            log_audit_action(user_id=current_user_id, action="KYC_REJECT", table_name="KYCRequest",
                             record_id=req_id, old={}, new=payload)
            consensus_publish(payload)
        except Exception:
            traceback.print_exc()

        return jsonify({"message": "KYC rejected", "req_id": req_id}), 200

    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({"error": "Error rejecting KYC", "details": str(e), "traceback": tb}), 500


