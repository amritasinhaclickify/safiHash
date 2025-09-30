# ai_engine/chat_routes.py
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta

# import models used later
from cooperative.models import Loan, RepaymentSchedule, Alert, TrustScore
import json

import re
import uuid
import traceback
import os
from cooperative.models import CooperativeGroup, GroupMembership
from hedera_sdk.wallet import create_hedera_account, fetch_wallet_balance, ensure_token_ready_for_account
from notifications.utils import push_notification, push_to_many
from flask_jwt_extended import jwt_required, get_jwt_identity
from cooperative.models import Deposit, LoanRequest, Repayment, TransactionLedger, VotingSession, VoteDetail
from cooperative.models import MemberBalance
from flask import current_app
from extensions import db
from users.models import User, KYCRequest
from ai_engine.kyc_verifier import verify_document
from hedera_sdk.token_service import transfer_hts_token
from utils.trust_utils import calculate_trust_score
from hedera_sdk.contracts import emit_trust_score 

# Use standardized consensus helper + audit logger
from utils.consensus_helper import publish_to_consensus as consensus_publish
from utils.audit_logger import log_audit_action
from werkzeug.utils import secure_filename
from uuid import uuid4
import hashlib
from hedera_sdk.kyc_service import upload_to_hfs
from users.models import User


def _make_slug(name: str) -> str:
    base = re.sub(r'[^a-z0-9]+', '-', name.strip().lower())
    base = base.strip('-') or 'group'
    tail = uuid.uuid4().hex[:6]
    return f"{base}-{tail}"


def _close_voting_if_quorum(session_obj):
    members = GroupMembership.query.filter_by(group_id=session_obj.group_id).count()
    yes = VoteDetail.query.filter_by(session_id=session_obj.id, choice="yes").count()
    no = VoteDetail.query.filter_by(session_id=session_obj.id, choice="no").count()
    total = yes + no
    quorum = (members // 2) + 1
    if total >= quorum or total == members:
        approved = yes > no
        session_obj.status = "approved" if approved else "rejected"
        session_obj.closed_at = datetime.utcnow()
        lr = LoanRequest.query.get(session_obj.loan_request_id)
        if lr: lr.status = session_obj.status
        db.session.commit()
        return True, approved, yes, no
    return False, None, yes, no


# --- Upload config (copy from kyc_routes) ---
ALLOWED_EXT = {"png", "jpg", "jpeg", "pdf", "txt"}
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB


def _is_allowed_filename(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXT


def _sha256_of_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


# Hedera account helpers (try importing real SDK wrappers; fallback to simple mocks)
try:
    from hedera_sdk import create_hedera_account, fetch_wallet_balance
except Exception:
    def create_hedera_account(user_id, metadata=None):
        return {"account_id": f"0.0.{1000 + int(user_id)}", "public_key": "PUB_PLACEHOLDER"}


    def fetch_wallet_balance(account_id):
        return {"account_id": account_id, "balance": 0.0}

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/message', methods=['POST'])
@jwt_required()
def chatbot_response():
    """
    Secure chat endpoint — requires JWT. Uses get_jwt_identity() to identify user.
    Supported (chat) commands: help, onboard, wallet, kyc
    """
    try:
        # ✅ Fix: JSON + FormData dono handle karo
        payload = request.get_json(silent=True) or {}

        # Agar file upload form-data hai, to form ka message use karo
        form_message = (request.form.get("message") or "").strip()
        json_message = (payload.get("message") or "").strip()
        raw_message = form_message or json_message

        user_message = raw_message.lower() if raw_message else ""
        current_user_id = get_jwt_identity()

        # Load user from DB (secure since JWT provided identity)
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({"response": "User not found."}), 404

        # -------- HELP / COMMANDS --------
        if "help" in user_message or user_message == "commands":
            return jsonify({
                "response": (
                    "📋 All available commands are now organized in the left sidebar menu. "
                    "👉 Expand each section (KYC, Groups, Deposits, Loans, Admin, Trust) to explore commands."
                )
            })

        # -------- ONBOARD (Hedera account create) --------
        if "onboard" in user_message or "create hedera" in user_message:
            if user.hedera_account_id:
                return jsonify({"response": f"Already onboarded ✅ Account: {user.hedera_account_id}"})

            info = create_hedera_account(user_id=current_user_id, metadata={"source": "chatbot"})
            user.hedera_account_id = info.get("account_id")
            db.session.commit()

            # Audit + consensus
            log_audit_action(
                user_id=current_user_id,
                action="Onboard Hedera",
                table_name="User",
                record_id=user.id,
                old={},
                new={"hedera_account_id": user.hedera_account_id}
            )
            consensus_publish({"user_id": current_user_id, "action": "ONBOARD", "account": user.hedera_account_id})

            return jsonify({"response": f"🚀 Hedera account created: {user.hedera_account_id}"})

        # -------- WALLET BALANCE --------
        if user_message.strip() in ["wallet", "balance"]:
            if not user.hedera_account_id:
                return jsonify({"response": "❌ Hedera account not found. Type 'onboard' to create one."})

            bal = fetch_wallet_balance(user.hedera_account_id)

            # 🔹 Sirf BHC token ka balance nikalo
            bhc_token_id = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
            bhc_decimals = int(os.getenv("BHC_DECIMALS", "2"))

            bhc_raw = bal.get("token_balances", {}).get(bhc_token_id)
            if bhc_raw is None:
                return jsonify({"response": f"💰 Balance for {user.hedera_account_id}: 0 BHC"})

            bhc_display = float(bhc_raw) / (10 ** bhc_decimals)
            return jsonify({"response": f"💰 Balance for {user.hedera_account_id}: {bhc_display} BHC"})

        # -------- KYC status check --------
        if "kyc status" in user_message:
            return jsonify({"response": f"Your KYC status: {user.kyc_status}"})

        # -------- KYC Flow (submit via chat) --------
        if "kyc" in user_message:
            # Protect against non-submission messages like "kyc status" (handled above)
            if user.kyc_status == "verified":
                return jsonify({
                    "response": "✅ Your KYC is verified! You are now a member of the Mint Bank and eligible to join the Co-operative Bank to save, borrow, and grow with your community."
                })

            # ---- FILE UPLOAD BRANCH ----
            if hasattr(request, "files") and request.files:
                local_path = None
                try:
                    file = request.files.get("file")
                    if not file or file.filename == "":
                        return jsonify({"response": "❌ No file provided for KYC."}), 400

                    if not _is_allowed_filename(file.filename):
                        return jsonify({"response": f"❌ File type not allowed. Allowed: {list(ALLOWED_EXT)}"}), 400

                    filename_safe = secure_filename(file.filename)
                    unique_name = f"{user.id}_{uuid4().hex}_{filename_safe}"
                    upload_dir = os.getenv("KYC_UPLOAD_FOLDER", "uploads")
                    os.makedirs(upload_dir, exist_ok=True)
                    local_path = os.path.join(upload_dir, unique_name)

                    file.save(local_path)
                    size = os.path.getsize(local_path)
                    if size > MAX_FILE_BYTES:
                        try:
                            os.remove(local_path)
                        except Exception:
                            pass
                        return jsonify({"response": f"❌ File too large (max {MAX_FILE_BYTES} bytes)."}), 413

                    local_hash = _sha256_of_file(local_path)

                    try:
                        result = upload_to_hfs(local_path)
                    except Exception as exc:
                        tb = traceback.format_exc()
                        try:
                            os.remove(local_path)
                        except Exception:
                            pass
                        return jsonify({"response": "❌ Hedera upload failed", "traceback": tb}), 502

                    file_id = result.get("file_id")
                    file_hash = result.get("hash")
                    if not file_id or not file_hash:
                        try:
                            os.remove(local_path)
                        except Exception:
                            pass
                        return jsonify({"response": f"❌ Invalid response from Hedera upload: {result}"}), 502

                    if local_hash != file_hash:
                        try:
                            os.remove(local_path)
                        except Exception:
                            pass
                        return jsonify({"response": "❌ Hash mismatch after upload."}), 500

                    # --- determine mode & initial status ---
                    from users.models import get_config
                    kyc_mode = (get_config("kyc_mode") or "manual").lower()
                    initial_status = "approved" if kyc_mode == "auto" else "pending"

                    # Update user record
                    user.kyc_file_id = file_id
                    user.kyc_file_hash = file_hash
                    user.kyc_status = "verified" if kyc_mode == "auto" else "pending"

                    # Find existing KYCRequest (latest) or create one with correct status
                    kyc_req = KYCRequest.query.filter_by(user_id=user.id).order_by(KYCRequest.id.desc()).first()
                    if kyc_req:
                        kyc_req.hedera_file_id = file_id
                        kyc_req.hedera_file_hash = file_hash
                        # if mode auto -> ensure request marked approved
                        if kyc_mode == "auto":
                            kyc_req.status = "approved"
                    else:
                        kyc_req = KYCRequest(
                            user_id=user.id,
                            document_type="National ID",
                            document_number=(request.form.get("document_number") or request.form.get("national_id")
                                             or (payload.get("document_number") if payload else None)
                                             or (payload.get("national_id") if payload else None) or "UNKNOWN"),
                            raw_data=json.dumps(request.form.to_dict() or {}),
                            status=initial_status,
                            submitted_at=datetime.utcnow(),
                            hedera_file_id=file_id,
                            hedera_file_hash=file_hash
                        )
                        db.session.add(kyc_req)

                    # persist everything in one commit
                    try:
                        db.session.commit()
                    except Exception as db_err:
                        db.session.rollback()
                        return jsonify({"response": "❌ DB error saving KYC data", "details": str(db_err)}), 500

                    # Audit log + consensus (publish actual status)
                    try:
                        log_audit_action(user_id=user.id, action="KYC_FILE_UPLOAD",
                                         table_name="User", record_id=user.id,
                                         old={}, new={"kyc_file_id": file_id, "kyc_file_hash": file_hash})
                        consensus_publish({
                            "action": "KYC_FILE_UPLOAD",
                            "user_id": user.id,
                            "file_id": file_id,
                            "hash": file_hash,
                            "status": kyc_req.status
                        })
                    except Exception:
                        traceback.print_exc()

                    try:
                        os.remove(local_path)
                    except Exception:
                        pass

                    return jsonify({
                        "response": f"✅ KYC file uploaded to Hedera. file_id={file_id}, hash={file_hash}",
                        "status": kyc_req.status,
                        "req_id": kyc_req.id
                    }), 201

                except Exception as exc:
                    tb = traceback.format_exc()
                    try:
                        if local_path and os.path.exists(local_path):
                            os.remove(local_path)
                    except Exception:
                        pass
                    return jsonify({"response": f"❌ KYC file flow failed: {str(exc)}", "traceback": tb}), 500

            # ---- TEXT/JSON KYC BRANCH ----
            doc = payload.get("document")
            if not doc:
                # parse inline text...
                ...
                doc = {"name": ..., "national_id": ..., "dob": ...}

            kyc_data = {
                "name": doc.get("name") if isinstance(doc, dict) else None,
                "national_id": doc.get("national_id") or doc.get("document_number") or doc.get("id_no") if isinstance(
                    doc, dict) else None,
                "dob": doc.get("dob") if isinstance(doc, dict) else None
            }

            kyc_result = verify_document(kyc_data)
            if kyc_result["status"] == "failed":
                return jsonify({"response": f"❌ KYC failed: {kyc_result['errors']}"})

            # determine mode & initial_status
            from users.models import get_config
            kyc_mode = (get_config("kyc_mode") or "manual").lower()
            initial_status = "approved" if kyc_mode == "auto" else "pending"

            try:
                kyc_req = KYCRequest(
                    user_id=user.id,
                    document_type="National ID",
                    document_number=kyc_data["national_id"],
                    raw_data=str(kyc_data),
                    status=initial_status,
                    submitted_at=datetime.utcnow()
                )
                db.session.add(kyc_req)

                # sync user status with mode
                if kyc_mode == "auto":
                    user.kyc_status = "verified"
                else:
                    user.kyc_status = "pending"

                db.session.commit()

            except Exception as db_err:
                db.session.rollback()
                tb = traceback.format_exc()
                return jsonify({"response": f"❌ DB error saving KYC request: {db_err}"}), 500

            # Audit + consensus publish the real status
            log_audit_action(
                user_id=user.id,
                action="KYC Submitted",
                table_name="KYCRequest",
                record_id=kyc_req.id,
                old={}, new=kyc_data
            )
            consensus_publish({
                "user_id": user.id,
                "action": "KYC_SUBMIT",
                "status": kyc_req.status,
                "req_id": kyc_req.id
            })

            return jsonify({
                "message": f"KYC submitted ({kyc_req.status}). Upload ID to speed approval." if kyc_req.status == "pending" else "KYC auto-approved",
                "status": kyc_req.status,
                "req_id": kyc_req.id,
                "next_step": "Please upload your ID document via chat with a file or use /api/kyc/upload."
            }), 201

        # -------- CREATE GROUP (updated: profit policy + notifications) --------
        if user_message.startswith("create group"):
            if user.kyc_status != "verified":
                return jsonify({"response": "❌ KYC required. Please complete KYC before creating a group."})

            parts = raw_message.split()
            # defaults
            name = None
            interest_rate = 0.10  # default 10% yearly
            min_balance = 0
            profit_reserve_pct = 10.0
            admin_cut_pct = 0.0
            distribute_on_profit = True

            try:
                idx_interest = parts.index("interest") if "interest" in parts else None
                idx_minbal = parts.index("minbalance") if "minbalance" in parts else None
                idx_prereserve = parts.index("profit_reserve") if "profit_reserve" in parts else None
                idx_admincut = parts.index("admin_cut") if "admin_cut" in parts else None
                idx_distribute = parts.index("distribute_on_profit") if "distribute_on_profit" in parts else None

                # group name = words between "create group" and first keyword
                candidate_idxs = [i for i in [idx_interest, idx_minbal, idx_prereserve, idx_admincut, idx_distribute] if
                                  i is not None]
                end_idx = min(candidate_idxs) if candidate_idxs else len(parts)
                name = " ".join(parts[2:end_idx])

                if idx_interest:
                    interest_rate = float(parts[idx_interest + 1])
                if idx_minbal:
                    min_balance = float(parts[idx_minbal + 1])
                if idx_prereserve:
                    profit_reserve_pct = float(parts[idx_prereserve + 1])
                if idx_admincut:
                    admin_cut_pct = float(parts[idx_admincut + 1])
                if idx_distribute:
                    val = parts[idx_distribute + 1].lower()
                    distribute_on_profit = val in {"true", "1", "yes", "y"}
            except Exception:
                return jsonify({
                    "response": "⚠️ Usage: create group <name> [interest <rate>] [minbalance <amt>] [profit_reserve <pct>] [admin_cut <pct>] [distribute_on_profit <true|false>]"}), 200

            if not name or len(name) < 3:
                return jsonify({"response": "ℹ️ Usage: create group <name> (min 3 chars)"}), 200

            import time
            acct, last_err = None, None
            for i in range(3):
                try:
                    acct = create_hedera_account(user_id=None, metadata={"type": "cooperative"})
                    if acct and acct.get("account_id"):
                        break
                except Exception as e:
                    last_err = str(e)
                time.sleep(i + 1)

            if not acct or not acct.get("account_id"):
                msg = "⚠️ Couldn't create group account due to network timeout. Please try again."
                if last_err:
                    msg += f" Details: {last_err}"
                return jsonify({"response": msg}), 200

            coop_acct = acct["account_id"]

            grp = CooperativeGroup(
                name=name,
                slug=_make_slug(name),
                created_by=user.id,
                cooperative_account_id=coop_acct,
                hedera_private_key=acct.get("private_key"),
                interest_rate=interest_rate,
                min_balance=min_balance,
                profit_reserve_pct=profit_reserve_pct,
                admin_cut_pct=admin_cut_pct,
                distribute_on_profit=distribute_on_profit
            )
            db.session.add(grp)
            db.session.flush()
            db.session.add(GroupMembership(group_id=grp.id, user_id=user.id, role="admin"))

            try:
                token_id = os.getenv("BHC_TOKEN_ID")
                op_key = os.getenv("HEDERA_OPERATOR_KEY")
                if token_id and op_key and acct.get("private_key"):
                    ensure_token_ready_for_account(
                        token_id=token_id,
                        account_id=coop_acct,
                        account_private_key=acct["private_key"],
                        kyc_grant_signing_key=op_key
                    )
            except Exception as e:
                # non-fatal
                print("⚠️ Group token-ready setup failed:", e)

            db.session.commit()

            # 🔔 Notifications: creator + all other verified users
            try:
                push_notification(user.id, f"🎉 Group created: {grp.name} (slug: {grp.slug})", "success")
            except Exception:
                pass

            try:
                verified_user_ids = [u.id for u in
                                     User.query.filter(User.kyc_status == "verified", User.id != user.id).all()]
                if verified_user_ids:
                    push_to_many(verified_user_ids,
                                 f"📢 New co-op group created: {grp.name} — use: join group {grp.slug}")
            except Exception:
                pass

            return jsonify({
                "response": (
                    f"✅ Group created: *{name}*\n"
                    f"Slug: `{grp.slug}`\n"
                    f"Group Account: `{coop_acct}`\n"
                    f"Interest Rate: {interest_rate}\n"
                    f"Minimum Balance: {min_balance} BHC\n"
                    f"Profit Reserve: {profit_reserve_pct}%\n"
                    f"Admin Cut: {admin_cut_pct}%\n"
                    f"Distribute On Profit: {distribute_on_profit}\n"
                    f"Members: 1 (you)."
                )
            }), 200

        # -------- JOIN GROUP --------
        if user_message.startswith("join group"):
            if user.kyc_status != "verified":
                return jsonify({"response": "❌ KYC required. Please complete KYC before joining a group."})

            slug = raw_message.split("join group", 1)[1].strip()
            if not slug:
                return jsonify({"response": "ℹ️ Usage: join group <slug>"})

            grp = CooperativeGroup.query.filter_by(slug=slug).first()
            if not grp:
                return jsonify({"response": "❌ Group not found."})

            existing = GroupMembership.query.filter_by(group_id=grp.id, user_id=user.id).first()
            if existing:
                return jsonify({"response": f"ℹ️ You are already a member of *{grp.name}*."})

            max_members = int(os.getenv("COOP_MAX_MEMBERS", "30"))
            if GroupMembership.query.filter_by(group_id=grp.id).count() >= max_members:
                return jsonify({"response": f"❌ Group is full (max {max_members} members)."})

            # Hedera wallet balance fetch
            if not user.hedera_account_id:
                return jsonify({"response": "❌ Hedera wallet not found. Type 'onboard' first."})

            bal = fetch_wallet_balance(user.hedera_account_id) or {}
            bhc_token_id = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
            bhc_decimals = int(os.getenv("BHC_DECIMALS", "2"))
            bhc_raw = (bal.get("token_balances") or {}).get(bhc_token_id)
            bhc_display = (float(bhc_raw) / (10 ** bhc_decimals)) if bhc_raw is not None else 0.0

            required_min = float(os.getenv("JOIN_MIN_WALLET_BHC", "50"))
            if bhc_display < required_min:
                return jsonify({
                    "response": f"❌ Need ≥ {required_min} BHC in your Hedera wallet to join. Current: {bhc_display:.2f} BHC"})

            # Add membership
            db.session.add(GroupMembership(group_id=grp.id, user_id=user.id, role="member"))
            db.session.commit()

            # ✅ Notification fix

            push_notification(user.id, f"✅ You joined {grp.name}", "success")

            admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
            if admin_ids:
                push_to_many(admin_ids, f"👥 {user.username} joined your group {grp.name}")

            return jsonify({
                "response": f"✅ Joined *{grp.name}*.\nGroup Account: `{grp.cooperative_account_id}`\nTip: deposit <amount> to {grp.slug}"
            }), 200

        # -------- LIST MY GROUPS (with dashboard link) --------
        if user_message in {"my groups", "groups", "list groups"}:
            memberships = GroupMembership.query.filter_by(user_id=user.id).all()
            if not memberships:
                return jsonify({"response": "ℹ️ You are not a member of any group. Create one: `create group <name>`"})
            lines = []
            for mem in memberships:
                grp = CooperativeGroup.query.get(mem.group_id)
                if not grp: continue
                lines.append(
                    f"- *{grp.name}* (slug: `{grp.slug}`) • role: {mem.role} • acct: `{grp.cooperative_account_id}` • "
                    f'<a href="/group/{grp.slug}" target="_blank" rel="noopener">Dashboard</a>'
                )
            return jsonify({"response": "👥 Your Groups:\n" + "\n".join(lines)})

        # -------- DEPOSIT (chat, on-chain BHC) --------
        if user_message.startswith("deposit"):
            if user.kyc_status != "verified":
                return jsonify({"response": "❌ KYC required."})

            parts = raw_message.split()
            amt, slug = None, None
            try:
                if len(parts) >= 4 and parts[1].replace(".", "").isdigit():
                    amt = float(parts[1])
                    slug = parts[3] if parts[2].lower() in {"bhc", "to"} else parts[2]
                elif len(parts) >= 3 and parts[1].replace(".", "").isdigit():
                    amt = float(parts[1])
                    slug = parts[2]
            except:
                amt = 0

            if not slug or amt is None or amt <= 0:
                return jsonify({"response": "ℹ️ Use: deposit <amount> bhc <slug>"})

            grp = CooperativeGroup.query.filter_by(slug=slug).first()
            if not grp:
                return jsonify({"response": "❌ Group not found."})
            if not GroupMembership.query.filter_by(group_id=grp.id, user_id=user.id).first():
                return jsonify({"response": "❌ Only members can deposit."})

            BHC_TOKEN_ID = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
            BHC_DECIMALS = int(os.getenv("BHC_DECIMALS", "2"))

            if not user.hedera_account_id or not user.hedera_private_key:
                return jsonify({"response": "❌ Your Hedera wallet not found. Run onboard first."})

            tx = transfer_hts_token(
                token_id=BHC_TOKEN_ID,
                from_account=user.hedera_account_id,
                from_privkey=user.hedera_private_key,
                to_account=grp.cooperative_account_id,
                amount=int(amt * (10 ** BHC_DECIMALS))
            )
            if tx.get("status") != "SUCCESS":
                return jsonify({"response": f"❌ Deposit failed: {tx}"}), 400

            dep = Deposit(group_id=grp.id, user_id=user.id, amount=amt)
            db.session.add(dep)
            db.session.flush()
            mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=user.id).first()
            if not mb:
                mb = MemberBalance(group_id=grp.id, user_id=user.id, total_deposit=amt)
                db.session.add(mb)
            else:
                mb.total_deposit = (mb.total_deposit or 0) + amt

            db.session.add(TransactionLedger(
                group_id=grp.id, user_id=user.id, ref_type="deposit",
                ref_id=dep.id, amount=amt, note="Chat deposit"
            ))
            db.session.commit()
            # 🔔 Notifications

            push_notification(user.id, f"✅ You deposited {amt} BHC into {grp.name}", "success")
            admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
            if admin_ids:
                push_to_many(admin_ids, f"💰 {user.username} deposited {amt} BHC into {grp.name}")

            # 🔹 Check against group's minimum balance
            if grp.min_balance and (mb.total_deposit or 0) < grp.min_balance:
                needed = grp.min_balance - (mb.total_deposit or 0)
                return jsonify({
                    "response": f"⚠️ Minimum balance for *{grp.name}* is {grp.min_balance} BHC.\n"
                                f"You still need {needed:.2f} BHC more."
                }), 200

            return jsonify({"response": f"✅ Deposited {amt} BHC into *{grp.name}*.", "tx": tx})

        # -------- WITHDRAW (chat) (improved: interest handling, pool support, DB safety, notifications via push_*) --------
        if user_message.startswith("withdraw"):
            if user.kyc_status != "verified":
                return jsonify({"response": "❌ KYC required."})

            parts = raw_message.split()
            if len(parts) < 3:
                return jsonify({"response": "ℹ️ Use: withdraw <amount> <slug>"})

            # validate amount
            try:
                amt = float(parts[1])
            except Exception:
                return jsonify({"response": "❌ Invalid amount."})

            slug = parts[2]
            grp = CooperativeGroup.query.filter_by(slug=slug).first()
            if not grp:
                return jsonify({"response": "❌ Group not found."})

            # wallet existence checks
            if not user.hedera_account_id or not user.hedera_private_key:
                return jsonify({"response": "❌ Your Hedera wallet not found. Run onboard first."})

            if not grp.cooperative_account_id or not grp.hedera_private_key:
                return jsonify({"response": "❌ Group vault not configured. Contact admin."})

            mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=user.id).first()
            if not mb or (mb.total_deposit or 0) <= 0:
                return jsonify({"response": "❌ No deposit found to withdraw."})

            if amt <= 0 or amt > (mb.total_deposit or 0):
                return jsonify({"response": "❌ Invalid withdrawal amount."})

            latest_deposit = Deposit.query.filter_by(group_id=grp.id, user_id=user.id).order_by(
                Deposit.created_at.desc()
            ).first()
            if not latest_deposit:
                return jsonify({"response": "❌ Deposit record not found."})

            months_diff = (datetime.utcnow() - latest_deposit.created_at).days / 30.0
            if months_diff < 6:
                return jsonify({"response": "❌ Withdrawal allowed only after 6 months."})

            # compute interest (legacy: simple half-year interest)
            interest_rate = float(getattr(grp, "interest_rate", 0.10) or 0.10)
            interest = round(amt * (interest_rate / 2.0), 8)  # keep precision, we round later for display

            # If group configured to distribute interest to profit pool, pay principal only now
            distribute_on_profit = bool(getattr(grp, "distribute_on_profit", False))
            if distribute_on_profit and interest > 0:
                payout = amt  # user receives principal only
            else:
                payout = amt + interest

            # on-chain transfer: group vault -> user
            BHC_TOKEN_ID = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
            BHC_DECIMALS = int(os.getenv("BHC_DECIMALS", "2"))

            try:
                tx = transfer_hts_token(
                    token_id=BHC_TOKEN_ID,
                    from_account=grp.cooperative_account_id,
                    from_privkey=grp.hedera_private_key,
                    to_account=user.hedera_account_id,
                    amount=int(round(payout * (10 ** BHC_DECIMALS)))
                )
            except Exception as e:
                return jsonify({"response": f"❌ On-chain transfer failed: {str(e)}"})

            # simple SDK success check if SDK returns dict
            if isinstance(tx, dict) and tx.get("status") and tx.get("status") != "SUCCESS":
                return jsonify({"response": f"❌ On-chain transfer did not succeed: {tx}"})

            # DB updates: reduce deposit, record interest or park to pool, ledger entry
            try:
                # reduce principal
                mb.total_deposit = float(mb.total_deposit or 0) - amt

                # if interest is to be paid now -> credit member interest
                if not distribute_on_profit and interest > 0:
                    mb.interest_earned = float(mb.interest_earned or 0) + interest
                    mb.total_withdrawn = float(mb.total_withdrawn or 0) + payout
                else:
                    # interest parked in group's profit pool (create/update)
                    mb.total_withdrawn = float(mb.total_withdrawn or 0) + payout

                db.session.add(mb)

                # ledger: withdrawal
                db.session.add(TransactionLedger(
                    group_id=grp.id, user_id=user.id, ref_type="withdraw",
                    ref_id=None, amount=float(payout),
                    note=f"Chat withdraw principal {amt} (interest_handled={'pool' if distribute_on_profit and interest > 0 else 'paid'})"
                ))

                # if interest goes to pool, update GroupProfitPool
                if distribute_on_profit and interest > 0:
                    from cooperative.models import GroupProfitPool
                    now = datetime.utcnow()
                    pool = GroupProfitPool.query.filter_by(group_id=grp.id).first()
                    if not pool:
                        pool = GroupProfitPool(
                            group_id=grp.id,
                            accrued_interest=interest,
                            expenses=0,
                            net_available=interest,
                            last_updated=now,
                            created_at=now
                        )
                        db.session.add(pool)
                    else:
                        pool.accrued_interest = float(pool.accrued_interest or 0) + interest
                        pool.net_available = float(pool.net_available or 0) + interest
                        pool.last_updated = now
                        db.session.add(pool)

                    db.session.add(TransactionLedger(
                        group_id=grp.id, user_id=user.id, ref_type="profit_accrual",
                        ref_id=None, amount=interest,
                        note=f"Interest {interest:.8f} parked to GroupProfitPool from chat-withdraw by user {user.id}"
                    ))

                db.session.commit()
            except Exception as db_exc:
                # DB failed after on-chain transfer -> attempt refund (best-effort)
                db.session.rollback()
                refund_msg = None
                try:
                    refund_tx = transfer_hts_token(
                        token_id=BHC_TOKEN_ID,
                        from_account=grp.cooperative_account_id,
                        from_privkey=grp.hedera_private_key,
                        to_account=user.hedera_account_id,
                        amount=int(round(payout * (10 ** BHC_DECIMALS)))
                    )
                    refund_msg = f"Refund attempted: {refund_tx}"
                except Exception as refund_exc:
                    refund_msg = f"Refund failed: {str(refund_exc)}"

                # notify user (best-effort) then return error in chat
                try:
                    push_notification(user.id, f"⚠️ Withdrawal processing failed. Refund status: {refund_msg}",
                                      "warning")
                except Exception:
                    pass

                return jsonify({"response": f"❌ DB error while recording withdrawal. Refund status: {refund_msg}"}), 500

            # Notifications on success (use only push_notification / push_to_many)
            try:
                if distribute_on_profit and interest > 0:
                    msg = f"🏦 You withdrew {amt} BHC. Interest {interest:.2f} BHC parked to group profit pool."
                    # notify user
                    try:
                        push_notification(user.id, msg, "info")
                    except Exception:
                        pass
                    # notify admins about pool accrual
                    try:
                        admin_ids = [m.user_id for m in
                                     GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
                        if admin_ids:
                            push_to_many(admin_ids, f"📈 {interest:.2f} BHC added to profit pool for {grp.name}.")
                    except Exception:
                        pass
                else:
                    msg = f"🏦 You withdrew {amt} BHC + {interest:.2f} interest = {payout:.2f} BHC"
                    try:
                        push_notification(user.id, msg, "success")
                    except Exception:
                        pass
            except Exception:
                pass

            # notify admins about withdrawal (always)
            try:
                admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
                if admin_ids:
                    push_to_many(admin_ids, f"💸 {user.username} withdrew {amt} BHC from {grp.name}")
            except Exception:
                pass

            return jsonify({"response": msg, "tx": tx})

        # -------- MY BALANCE (chat) --------
        if user_message.startswith("my balance") or user_message == "balance":
            parts = raw_message.split()
            slug = parts[-1] if len(parts) > 2 else None
            if not slug:
                return jsonify({"response": "ℹ️ Usage: my balance <group_slug>"})

            grp = CooperativeGroup.query.filter_by(slug=slug).first()
            if not grp:
                return jsonify({"response": "❌ Group not found."})

            mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=user.id).first()
            if not mb:
                return jsonify({"response": f"ℹ️ You have no balance in *{grp.name}*."})

            net = float(mb.total_deposit or 0) + float(mb.interest_earned or 0) - float(mb.total_withdrawn or 0)
            return jsonify({
                "response": f"💰 Balance in *{grp.name}*:\nDeposits: {mb.total_deposit}\nInterest: {mb.interest_earned}\nWithdrawn: {mb.total_withdrawn}\n➡️ Net: {net}"})

        # -------- LOAN REQUEST (chat) --------
        if user_message.startswith("loan "):
            if user.kyc_status != "verified":
                return jsonify({"response": "❌ KYC required."})

            parts = raw_message.split(maxsplit=3)  # loan slug amount [purpose...]
            if len(parts) < 3:
                return jsonify({"response": "ℹ️ Use: loan <slug> <amount> [purpose]"})
            _, slug, amt_str, *rest = parts
            try:
                amt = float(amt_str)
            except:
                return jsonify({"response": "❌ Invalid amount."})
            purpose = rest[0] if rest else ""

            grp = CooperativeGroup.query.filter_by(slug=slug).first()
            if not grp:
                return jsonify({"response": "❌ Group not found."})
            if not GroupMembership.query.filter_by(group_id=grp.id, user_id=user.id).first():
                return jsonify({"response": "❌ Only members can request loan."})
            if amt <= 0:
                return jsonify({"response": "❌ Invalid loan amount."})

            # create loan request + voting session
            lr = LoanRequest(group_id=grp.id, user_id=user.id, amount=amt, status="pending", purpose=purpose)
            db.session.add(lr)
            db.session.flush()
            vs = VotingSession(group_id=grp.id, loan_request_id=lr.id, status="ongoing")
            db.session.add(vs)
            db.session.commit()

            # notify all group members to vote (except requester)
            try:
                member_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id).all() if
                              m.user_id != user.id]
                if member_ids:
                    push_to_many(member_ids,
                                 f"🗳️ New loan request #{lr.id} in {grp.name}: {amt} BHC — Vote: vote {lr.id} yes|no")
            except Exception as e:
                # non-fatal: print/log and continue
                print("⚠️ notify-members failed (chat loan):", e)

            # acknowledge requester (chat)
            try:
                push_notification(user.id, f"📌 Loan request {amt} BHC created in {grp.name}", "info")
            except Exception:
                pass

            return jsonify(
                {"response": f"📌 Loan request {amt} created for *{grp.name}* — voting started (Req #{lr.id})."})

        # -------- ADMIN APPROVE PAYMENT (chat) --------
        if user_message.startswith("approve payment"):
            parts = raw_message.split()
            if len(parts) < 3:
                return jsonify({"response": "ℹ️ Use: approve payment <repayment_id> [apply_amount]"})
            try:
                repayment_id = int(parts[2])
            except:
                return jsonify({"response": "❌ Invalid repayment id."})

            # optional: parse apply_amount -> approve payment <id> <amount>
            apply_amount = None
            if len(parts) >= 4:
                try:
                    apply_amount = float(parts[3])
                except:
                    return jsonify({"response": "❌ Invalid apply_amount. Use a number."})

            # ✅ group-scoped admin check using PaymentAudit -> group_id
            audit = PaymentAudit.query.filter_by(payment_id=repayment_id).first()
            if not audit:
                return jsonify({"response": "❌ Payment audit missing - manual reconcile needed"}), 404

            is_admin = GroupMembership.query.filter_by(
                group_id=audit.group_id, user_id=user.id, role="admin"
            ).count() > 0
            if not is_admin:
                return jsonify({"response": "❌ Only this group's admin can approve this payment."}), 403

            with current_app.test_client() as c:
                r = c.post(
                    f"/api/coops/admin/payment/{repayment_id}/approve",
                    headers={"Authorization": request.headers.get("Authorization")},
                    json=({"apply_amount": apply_amount} if apply_amount is not None else None)
                )
                data = r.get_json() or {}
                if r.status_code >= 400:
                    return jsonify({"response": f"❌ {data.get('error', 'Approval failed')}"})
                msg = data.get("message") or "✅ Payment approved"
                if "applied" in data or "excess" in data:
                    msg += f" (applied: {data.get('applied', 0)}, excess: {data.get('excess', 0)})"
                return jsonify({"response": msg})

        # -------- ADMIN REJECT PAYMENT (chat) --------
        if user_message.startswith("reject payment"):
            parts = raw_message.split()
            if len(parts) < 3:
                return jsonify({"response": "ℹ️ Use: reject payment <repayment_id>"})
            try:
                repayment_id = int(parts[2])
            except:
                return jsonify({"response": "❌ Invalid repayment id."})

            is_admin = GroupMembership.query.filter_by(user_id=user.id, role="admin").count() > 0
            if not is_admin:
                return jsonify({"response": "❌ Only admins can reject payments."})

            with current_app.test_client() as c:
                r = c.post(
                    f"/api/coops/admin/payment/{repayment_id}/reject",
                    headers={"Authorization": request.headers.get("Authorization")}
                )
                data = r.get_json() or {}
                if r.status_code >= 400:
                    return jsonify({"response": f"❌ {data.get('error', 'Rejection failed')}"}), r.status_code
                return jsonify(
                    {"response": data if isinstance(data, str) else data.get('message', '✅ Payment rejected')})

        # -------- ADMIN LIST PENDING PAYMENTS (chat) --------
        if user_message in {"pending payments", "list pending payments"}:

            with current_app.test_client() as c:
                r = c.get(f"/api/coops/admin/payments/pending",
                          headers={"Authorization": request.headers.get("Authorization")})
                data = r.get_json()
                if "error" in data:
                    return jsonify({"response": f"❌ {data['error']}"})
                if not data:
                    return jsonify({"response": "✅ No pending suspicious payments."})
                lines = [
                    f"⚠️ Payment #{p['payment_id']} from payer {p['payer_id']} for loan {p['loan_id']} ({p['amount']} BHC)"
                    for p in data]
                return jsonify({"response": "📝 Pending Payments:\n" + "\n".join(lines)})
        # -------- ADMIN VIEW GROUP CREDITS (chat) --------
        if user_message.startswith("credits "):
            parts = raw_message.split()
            if len(parts) < 2:
                return jsonify({"response": "ℹ️ Use: credits <group_id>"})
            try:
                group_id = int(parts[1])
            except:
                return jsonify({"response": "❌ Invalid group_id."})

            with current_app.test_client() as c:
                r = c.get(f"/api/coops/admin/group/{group_id}/credits",
                          headers={"Authorization": request.headers.get("Authorization")})
                data = r.get_json()
                if "error" in data:
                    return jsonify({"response": f"❌ {data['error']}"})
                if not data:
                    return jsonify({"response": "ℹ️ No credits found for this group."})

                lines = [f"💳 Credit #{cr['id']} • user {cr['user_id']} • {cr['amount']} BHC • src:{cr['source']}"
                         for cr in data]
                return jsonify({"response": "💳 Group Credits:\n" + "\n".join(lines)})

        # -------- ADMIN APPLY CREDIT (chat) --------
        if user_message.startswith("apply credit"):
            parts = raw_message.split()
            if len(parts) < 5:
                return jsonify({"response": "ℹ️ Use: apply credit <credit_id> <loan_id> <amount>"})
            try:
                credit_id = int(parts[2])
                loan_id = int(parts[3])
                amt = float(parts[4])
            except:
                return jsonify({"response": "❌ Invalid input. Use: apply credit <credit_id> <loan_id> <amount>"})

            with current_app.test_client() as c:
                r = c.post(f"/api/coops/admin/credit/{credit_id}/apply",
                           headers={"Authorization": request.headers.get("Authorization")},
                           json={"loan_id": loan_id, "amount": amt})
                data = r.get_json()
                if "error" in data:
                    return jsonify({"response": f"❌ {data['error']}"})
                return jsonify({"response": f"✅ Applied {amt} BHC from credit #{credit_id} to Loan #{loan_id}."})

        # -------- LOAN DISBURSAL (chat, admin only) (improved: safety, notifications, audit) --------
        if user_message.startswith("disburse "):
            parts = raw_message.split()
            if len(parts) < 2:
                return jsonify({"response": "ℹ️ Use: disburse <loan_request_id>"})
            try:
                lrid = int(parts[1])
            except:
                return jsonify({"response": "❌ Invalid loan request id."})

            lr = LoanRequest.query.get(lrid)
            if not lr:
                return jsonify({"response": "❌ Loan request not found."})

            # find Loan record created during approval
            loan = Loan.query.filter_by(loan_request_id=lrid).first()
            if not loan:
                return jsonify(
                    {"response": "❌ Loan record not found. Voting-approved loans should create a Loan entry."})

            # allow disbursal only if loan is approved (not already active/closed)
            if loan.status == "active":
                return jsonify({"response": f"ℹ️ Loan already disbursed (loan_id: {loan.id})."})
            if loan.status != "approved":
                return jsonify({"response": f"❌ Loan in unexpected state: {loan.status}"}), 400

            grp = CooperativeGroup.query.get(loan.group_id)
            if not grp:
                return jsonify({"response": "❌ Group not found."})

            membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=user.id).first()
            if not membership or membership.role != "admin":
                return jsonify({"response": "❌ Only group admins can disburse loans."})

            borrower = User.query.get(loan.user_id)
            if not borrower or not borrower.hedera_account_id:
                return jsonify({"response": "❌ Borrower Hedera account not found."})

            # Optional: quick vault liquidity check (best-effort)
            try:
                bhc_token_id = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
                bhc_decimals = int(os.getenv("BHC_DECIMALS", "2"))
                vault_bal = fetch_wallet_balance(grp.cooperative_account_id) or {}
                vault_raw = (vault_bal.get("token_balances") or {}).get(bhc_token_id)
                vault_display = (float(vault_raw) / (10 ** bhc_decimals)) if vault_raw is not None else 0.0
                if vault_display < float(loan.principal):
                    return jsonify({
                        "response": f"❌ Insufficient group vault balance ({vault_display} BHC) to disburse {loan.principal} BHC."})
            except Exception:
                # ignore balance-check failures (best-effort); continue to transfer attempt
                pass

            BHC_TOKEN_ID = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
            BHC_DECIMALS = int(os.getenv("BHC_DECIMALS", "2"))

            # Perform on-chain transfer (vault -> borrower)
            try:
                tx = transfer_hts_token(
                    token_id=BHC_TOKEN_ID,
                    from_account=grp.cooperative_account_id,
                    from_privkey=grp.hedera_private_key,
                    to_account=borrower.hedera_account_id,
                    amount=int(float(loan.principal) * (10 ** BHC_DECIMALS))
                )
            except Exception as e:
                return jsonify({"response": f"❌ On-chain transfer failed: {str(e)}"})

            # SDK quick check
            if isinstance(tx, dict) and tx.get("status") and tx.get("status") != "SUCCESS":
                return jsonify({"response": f"❌ On-chain transfer did not succeed: {tx}"}), 502

            # Now persist loan activation, schedule, ledger (DB). If DB fails we cannot auto-reverse the on-chain transfer.
            try:
                loan.status = "active"
                loan.disbursed_at = datetime.utcnow()
                db.session.add(loan)
                db.session.flush()

                # create repayment schedule using loan.tenure_months
                interest_rate = float(grp.interest_rate or 0.10)
                tenure = int(loan.tenure_months or 12)
                monthly_interest = (float(loan.principal) * interest_rate) / 12.0
                monthly_principal = float(loan.principal) / max(1, tenure)
                for i in range(1, tenure + 1):
                    due_date = datetime.utcnow() + timedelta(days=30 * i)
                    db.session.add(RepaymentSchedule(
                        loan_id=loan.id,
                        installment_no=i,
                        due_date=due_date,
                        due_amount=monthly_principal + monthly_interest,
                        principal_component=monthly_principal,
                        interest_component=monthly_interest
                    ))

                # update LoanRequest status to disbursed
                lr.status = "disbursed"
                db.session.add(lr)

                # ledger entry
                db.session.add(TransactionLedger(
                    group_id=grp.id,
                    user_id=loan.user_id,
                    ref_type="loan_disbursal",
                    ref_id=loan.id,
                    amount=float(loan.principal),
                    note=f"Loan disbursed {float(loan.principal)} BHC"
                ))

                db.session.commit()
            except Exception as db_exc:
                db.session.rollback()
                # IMPORTANT: we cannot reliably reverse an on-chain transfer here (we don't have borrower's private key).
                # So we record the failure, raise admin alerts and log audit/consensus for manual reconciliation.
                try:
                    # admin notification (urgent)
                    admin_ids = [m.user_id for m in
                                 GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
                    alert_msg = (f"⚠️ Disbursal DB failure for LoanRequest #{lrid}. "
                                 f"On-chain tx: {tx}. Admin reconciliation required.")
                    if admin_ids:
                        push_to_many(admin_ids, alert_msg)
                    push_notification(user.id, alert_msg, "warning")
                    # also notify borrower
                    push_notification(borrower.id,
                                      f"⚠️ Your loan disbursal encountered an internal error. Admins will reconcile.",
                                      "warning")
                except Exception:
                    pass

                # audit + consensus publish (so operations team can track)
                try:
                    log_audit_action(
                        user_id=user.id,
                        action="Disbursal DB commit failed",
                        table_name="Loan",
                        record_id=loan.id if loan and loan.id else None,
                        old={},
                        new={"loan_request_id": lrid, "onchain_tx": str(tx), "error": str(db_exc)}
                    )
                    consensus_publish(
                        {"action": "DISBURSAL_DB_FAIL", "loan_request_id": lrid, "tx": tx, "error": str(db_exc)})
                except Exception:
                    pass

                return jsonify({
                    "response": ("❌ Disbursal succeeded on-chain but failed to record in DB. "
                                 "Manual admin reconciliation required. Admins have been notified."),
                    "db_error": str(db_exc),
                    "onchain_tx": tx
                }), 500

            # Success: notify borrower, admin and log audit/consensus
            try:
                push_notification(borrower.id, f"✅ Your loan #{loan.id} of {loan.principal} BHC has been disbursed.",
                                  "success")
                push_notification(user.id, f"📤 You disbursed {loan.principal} BHC loan to {borrower.username}", "info")
                admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
                if admin_ids:
                    push_to_many(admin_ids,
                                 f"📢 Loan #{loan.id} disbursed to {borrower.username} ({loan.principal} BHC)")
            except Exception:
                pass

            # audit + consensus publish for success
            try:
                log_audit_action(
                    user_id=user.id,
                    action="Loan Disbursed",
                    table_name="Loan",
                    record_id=loan.id,
                    old={},
                    new={"status": loan.status, "disbursed_at": loan.disbursed_at.isoformat(), "onchain_tx": str(tx)}
                )
                consensus_publish({"action": "DISBURSE", "loan_id": loan.id, "tx": tx, "by": user.id})
            except Exception:
                pass

            return jsonify({"response": f"✅ Loan disbursed to *{borrower.username}* ({loan.principal} BHC).", "tx": tx})

        # -------- LOAN REPAYMENT (chat, borrower or third-party with admin approval) --------
        if user_message.startswith("repay "):
            parts = raw_message.split()
            if len(parts) < 3:
                return jsonify({"response": "ℹ️ Use: repay <loan_request_id> <amount>"})

            try:
                lrid = int(parts[1])
                amt = float(parts[2])
            except:
                return jsonify({"response": "❌ Invalid input. Use: repay <loan_request_id> <amount>"})

            if amt <= 0:
                return jsonify({"response": "❌ Repayment amount must be positive."})

            # Call backend repay endpoint instead of duplicating logic
            with current_app.test_client() as client:
                headers = {
                    "Authorization": request.headers.get("Authorization") or request.environ.get("HTTP_AUTHORIZATION")}

                resp = client.post(
                    f"/api/coops/loan/{lrid}/repay",
                    json={"amount": amt},
                    headers=headers
                )
                data = resp.get_json() or {}
                status = resp.status_code

            # Notifications + responses
            if status == 201:
                msg = data.get("message") or f"💵 Repayment {amt} BHC processed."
                return jsonify({"response": msg})

            elif status == 202:
                msg = data.get("message") or f"⏳ Repayment {amt} BHC received, pending admin approval."
                return jsonify({"response": msg})

            elif status >= 400:
                err = data.get("error") or "❌ Repayment failed."
                return jsonify({"response": f"{err}"})

            else:
                return jsonify({"response": data})

            # -------- TRUST SCORE (chat) --------
        if user_message.startswith("trustscore"):
            parts = raw_message.split()
            target_user_id = None

            if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() == "me"):
                # self
                target_user_id = user.id
            elif len(parts) == 2:
                try:
                    target_user_id = int(parts[1])
                except:
                    return jsonify({"response": "❌ Invalid user_id. Use: trustscore [user_id|me]"})

            # fetch trust score
            from cooperative.models import TrustScore
            ts = TrustScore.query.filter_by(user_id=target_user_id).first()

            if not ts:
                return jsonify({"response": f"ℹ️ No Trust Score found for user {target_user_id}."})

            # if checking someone else, ensure current user is admin in at least one group
            if target_user_id != user.id:
                admin_groups = GroupMembership.query.filter_by(user_id=user.id, role="admin").count()
                if admin_groups == 0:
                    return jsonify({"response": "❌ Only admins can view other members' trust scores."})

            # 🔔 Send notification

            push_notification(user.id, f"📊 Trust Score checked: {ts.score:.2f}", "info")

            return jsonify({
                "response": f"📊 Trust Score for user {target_user_id}: {ts.score:.2f}"
            })

        # -------- ALERTS (chat, member view) (improved: scoped, dedup, notify) --------
        if user_message.startswith("alerts "):
            parts = raw_message.split()
            if len(parts) < 2:
                return jsonify({"response": "ℹ️ Use: alerts <group_slug>"})

            slug = parts[1]
            grp = CooperativeGroup.query.filter_by(slug=slug).first()
            if not grp:
                return jsonify({"response": "❌ Group not found."})

            # membership check (must be member of that group)
            membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=user.id).first()
            if not membership:
                return jsonify({"response": "❌ You are not a member of this group."})

            lines = []

            # 1) stored alerts (scoped to this group if available)
            try:
                stored_alerts = Alert.query.filter_by(user_id=user.id, group_id=grp.id).order_by(
                    Alert.created_at.desc()).limit(25).all()
            except Exception:
                # fallback to user-wide alerts if group-scoped field doesn't exist
                stored_alerts = Alert.query.filter_by(user_id=user.id).order_by(Alert.created_at.desc()).limit(25).all()

            for a in stored_alerts:
                lines.append(f"[{a.level.upper()}] {a.message} ({a.created_at.strftime('%Y-%m-%d')})")

            # 2) runtime checks (overdue installments for this group's loans)
            try:
                overdue = (RepaymentSchedule.query.join(Loan, RepaymentSchedule.loan_id == Loan.id)
                           .filter(
                    Loan.group_id == grp.id,
                    Loan.user_id == user.id,
                    RepaymentSchedule.status == "due",
                    RepaymentSchedule.due_date < datetime.utcnow()
                ).all())
                for r in overdue:
                    lines.append(
                        f"⚠️ Overdue installment #{r.installment_no} for Loan {r.loan_id} (due {r.due_date.date()})")
            except Exception:
                # don't break alerts flow on query error
                pass

            # 3) trust score check (global per-user)
            try:
                ts = TrustScore.query.filter_by(user_id=user.id).first()
                if ts and ts.score < 30:
                    lines.append(f"❌ Low trust score ({ts.score}). Future loans may be restricted.")
            except Exception:
                pass

            # 4) min-balance check for this group
            try:
                mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=user.id).first()
                if getattr(grp, "min_balance", None) and (
                        not mb or float(mb.total_deposit or 0) < float(grp.min_balance or 0)):
                    needed = round(float(grp.min_balance or 0) - float(mb.total_deposit or 0),
                                   2) if mb else grp.min_balance
                    lines.append(
                        f"ℹ️ Your deposits are below the group minimum balance ({grp.min_balance} BHC). You need ~{needed:.2f} BHC more.")
            except Exception:
                pass

            # dedupe & limit results shown to user
            seen = set()
            deduped = []
            for l in lines:
                if l not in seen:
                    deduped.append(l)
                    seen.add(l)
            deduped = deduped[:50]

            if not deduped:
                return jsonify({"response": "✅ No alerts. Everything looks good!"})

            # Optionally: push the top alert as a lightweight notification (do not spam)
            try:
                top = deduped[0]
                push_notification(user.id, f"🔔 Alerts checked: {top}", "info")
            except Exception:
                pass

            # Return full list
            return jsonify({"response": "🔔 Alerts:\n" + "\n".join(deduped)})

        # -------- ADMIN: PUSH SINGLE TRUSTSCORE (by user_id + group_slug) --------
        if user_message.startswith("push trustscore "):
            try:
                parts = raw_message.split()
                # push trustscore <user_id> <group_slug>
                if len(parts) < 3:
                    return jsonify({"response": "ℹ️ Use: push trustscore <user_id> <group_slug>"}), 200

                try:
                    target_user_id = int(parts[2])
                except Exception:
                    return jsonify({"response": "❌ Invalid user_id"}), 400

                # group_slug may have hyphens etc; join remaining parts back
                group_slug = " ".join(parts[3:]).strip()
                if not group_slug:
                    return jsonify({"response": "❌ Missing <group_slug>"}), 400

                grp = CooperativeGroup.query.filter_by(slug=group_slug).first()
                if not grp:
                    return jsonify({"response": f"❌ Group not found for slug '{group_slug}'"}), 404

                # caller must be admin of this group
                caller_id = get_jwt_identity()
                is_admin = GroupMembership.query.filter_by(group_id=grp.id, user_id=caller_id, role="admin").count() > 0
                if not is_admin:
                    return jsonify({"response": "❌ Only this group's admin can push trustscore on-chain"}), 403

                # target must be a member of this group
                if not GroupMembership.query.filter_by(group_id=grp.id, user_id=target_user_id).first():
                    return jsonify({"response": "❌ Target user is not a member of this group"}), 400

                # calculate
                result = calculate_trust_score(user_id=target_user_id, group_id=grp.id, window_days=7)
                score = float(result.get("overall") or result.get("final") or 0.0)
                score_x100 = int(round(score * 100))

                # contract addr
                addr = os.getenv("COOPTRUST_CONTRACT")
                if not addr:
                    return jsonify({"response": "⚠️ COOPTRUST_CONTRACT not set in env"}), 500

                # push on-chain
                tx = emit_trust_score(addr, target_user_id, grp.id, score_x100, f"manual-push:{group_slug}")

                ok = isinstance(tx, dict) and (tx.get("status") in (1, "success", "SUCCESS"))
                tx_hash = (tx or {}).get("txHash")

                if ok and tx_hash:
                    return jsonify(
                        {"response": f"✅ Pushed trustscore {score:.2f} for user {target_user_id} @ {group_slug}",
                         "tx": tx_hash}), 200
                else:
                    return jsonify({"response": f"⚠️ Push attempted but not confirmed", "detail": tx}), 502

            except Exception as e:
                return jsonify({"response": f"❌ Push failed: {str(e)}"}), 500

        # -------- VOTE (chat) --------
        if user_message.startswith("vote "):
            parts = raw_message.split()
            if len(parts) < 3:
                return jsonify({"response": "ℹ️ Use: vote <loan_request_id> yes|no"})
            _, lrid_str, choice = parts[:3]
            try:
                lrid = int(lrid_str)
            except:
                return jsonify({"response": "❌ Invalid request id."})
            choice = choice.lower()
            if choice not in {"yes", "no"}:
                return jsonify({"response": "❌ Vote must be yes/no."})

            vs = VotingSession.query.filter_by(loan_request_id=lrid, status="ongoing").first()
            if not vs:
                return jsonify({"response": "❌ No ongoing voting."})

            if not GroupMembership.query.filter_by(group_id=vs.group_id, user_id=user.id).first():
                return jsonify({"response": "❌ Only members can vote."})

            if VoteDetail.query.filter_by(session_id=vs.id, voter_id=user.id).first():
                return jsonify({"response": "ℹ️ You already voted on this request."})

            db.session.add(VoteDetail(session_id=vs.id, voter_id=user.id, choice=choice))
            db.session.commit()

            # close voting if quorum reached — use existing helper but also ensure Loan creation + notifications
            closed, approved, yes, no = _close_voting_if_quorum(vs)
            if closed:
                status = "approved ✅" if approved else "rejected ❌"

                # fetch the loan request and ensure Loan row created when approved (idempotent)
                lr = LoanRequest.query.get(lrid)
                if lr and approved:
                    try:
                        existing_loan = Loan.query.filter_by(loan_request_id=lr.id).first()
                        if not existing_loan:
                            interest_rate = float(CooperativeGroup.query.get(lr.group_id).interest_rate or 0.10)
                            loan = Loan(
                                loan_request_id=lr.id,
                                group_id=lr.group_id,
                                user_id=lr.user_id,
                                principal=float(lr.amount),
                                interest_rate_apy=interest_rate * 100.0,
                                tenure_months=12,
                                status="approved",
                                created_at=datetime.utcnow()
                            )
                            db.session.add(loan)
                            db.session.commit()

                            # notify group members to disburse (admins) and inform group that loan is approved
                            try:
                                # notify admins to disburse
                                admin_ids = [m.user_id for m in
                                             GroupMembership.query.filter_by(group_id=lr.group_id, role="admin").all()]
                                if admin_ids:
                                    push_to_many(admin_ids,
                                                 f"🔔 Loan #{loan.id} approved for {loan.principal} BHC — run: disburse {lr.id}")

                                # notify group members to inform vote outcome (except requester)
                                member_ids = [m.user_id for m in
                                              GroupMembership.query.filter_by(group_id=lr.group_id).all() if
                                              m.user_id != lr.user_id]
                                if member_ids:
                                    push_to_many(member_ids,
                                                 f"🗳️ Loan request #{lr.id} has been approved ✅. Admins can disburse using: disburse {lr.id}")
                            except Exception:
                                pass
                    except Exception as e:
                        # non-fatal: log / return message but don't break
                        print("⚠️ create-loan-after-vote failed:", e)

                return jsonify({"response": f"🗳️ Vote recorded. Voting closed — {status}. (yes:{yes} no:{no})"})
            return jsonify({"response": f"🗳️ Vote recorded. Voting ongoing. (yes:{yes} no:{no})"})

        # -------- FALLBACK for unknown commands --------
        # If no handler matched, return a friendly fallback (inside try:)
        return jsonify({
            "response": (
                f"❌ Unknown command: '{raw_message}'.\n"
                "👉 Type 'help' to see available commands or open the sidebar."
            )
        }), 200
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({"response": f"❌ Error processing message: {str(e)}", "traceback": tb}), 500




