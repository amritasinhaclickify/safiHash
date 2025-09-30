# cooperative/routes.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
import os
import re
import uuid
import math

BHC_TOKEN_ID = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
BHC_DECIMALS = int(os.getenv("BHC_DECIMALS", "2"))

from extensions import db
from cooperative.models import (
    CooperativeGroup, GroupMembership,
    Deposit, LoanRequest, Repayment, TrustScore, Alert,
    TransactionLedger, VotingSession, VoteDetail
)
from users.models import User
from hedera_sdk.wallet import create_hedera_account, ensure_token_ready_for_account, fetch_wallet_balance
from hedera_sdk.smart_contracts import create_loan_onchain, repay_loan_onchain
from notifications.routes import create_notification
from cooperative.models import MemberBalance
from cooperative.models import Loan, RepaymentSchedule
from cooperative.models import TrustScoreHistory
from notifications.utils import push_notification, push_to_many
from cooperative.models import CreditLedger, PaymentAudit, PaymentApproval
from hedera_sdk.contracts import emit_trust_score
from hedera_sdk.token_service import transfer_hts_token
from utils.trust_utils import calculate_trust_score
from flask import jsonify
from cooperative.models import HCSMessageLog, ContractEventLog, GroupAccountLink
from flask import render_template
from cooperative.models import GroupProfitPool
from utils.audit_logger import log_audit_action
from utils.consensus_helper import publish_to_consensus as consensus_publish


coop_bp = Blueprint("cooperative", __name__, url_prefix="/api/coops")


def _bhc_display_from_balance_dict(bal: dict) -> float:
    """
    Hedera wallet balance dict se BHC ka display amount (decimals applied) nikaalo.
    """
    bhc_token_id = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
    bhc_decimals = int(os.getenv("BHC_DECIMALS", "2"))
    raw = (bal.get("token_balances") or {}).get(bhc_token_id)
    return (float(raw) / (10 ** bhc_decimals)) if raw is not None else 0.0


def _make_slug(name: str) -> str:
    base = re.sub(r'[^a-z0-9]+', '-', name.strip().lower())
    base = base.strip('-') or 'group'
    tail = uuid.uuid4().hex[:6]
    return f"{base}-{tail}"


def _close_voting_if_quorum(session_obj):
    members = GroupMembership.query.filter_by(group_id=session_obj.group_id).count()
    yes = VoteDetail.query.filter_by(session_id=session_obj.id, choice="yes").count()
    no = VoteDetail.query.filter_by(session_id=session_obj.id, choice="no").count()
    total_votes = yes + no
    quorum_needed = (members // 2) + 1  # simple majority

    if total_votes >= quorum_needed or total_votes == members:
        approved = yes > no
        session_obj.status = "approved" if approved else "rejected"
        session_obj.closed_at = datetime.utcnow()
        lr = LoanRequest.query.get(session_obj.loan_request_id)
        if lr:
            lr.status = "approved" if approved else "rejected"
        db.session.commit()
        return {"closed": True, "approved": approved, "yes": yes, "no": no}
    return {"closed": False, "approved": None, "yes": yes, "no": no}


@coop_bp.route("/<slug>/join", methods=["POST"])
@jwt_required()
def join_group(slug):
    """
    Join an existing group by slug.
    Requires: user KYC=verified
    Enforces: optional max members (COOP_MAX_MEMBERS, default 30)
    Enforces: user's Hedera wallet must hold >= JOIN_MIN_WALLET_BHC BHC (default 10).
    """
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.kyc_status != "verified":
        return jsonify({"error": "KYC required"}), 403
    if not user.hedera_account_id:
        return jsonify({"error": "User Hedera wallet missing"}), 400

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    # already a member?
    existing = GroupMembership.query.filter_by(group_id=grp.id, user_id=user.id).first()
    if existing:
        return jsonify({"message": "Already a member", "group": {"name": grp.name, "slug": grp.slug}}), 200

    # capacity check
    max_members = int(os.getenv("COOP_MAX_MEMBERS", "30"))
    count = GroupMembership.query.filter_by(group_id=grp.id).count()
    if count >= max_members:
        return jsonify({"error": f"Group is full (max {max_members} members)"}), 400

    # 🔒 Wallet-min BHC check BEFORE joining
    try:
        required_min = float(os.getenv("JOIN_MIN_WALLET_BHC", "10"))
        bal = fetch_wallet_balance(user.hedera_account_id) or {}
        bhc_token_id = os.getenv("BHC_TOKEN_ID", BHC_TOKEN_ID)
        bhc_decimals = int(os.getenv("BHC_DECIMALS", str(BHC_DECIMALS)))
        bhc_raw = (bal.get("token_balances") or {}).get(bhc_token_id)
        bhc_display = (float(bhc_raw) / (10 ** bhc_decimals)) if bhc_raw is not None else 0.0
        if bhc_display < required_min:
            return jsonify({
                "error": f"Minimum {required_min} BHC required in your wallet to join. Current: {bhc_display:.2f} BHC."
            }), 403
    except Exception as e:
        return jsonify({"error": f"Failed to verify wallet balance: {e}"}), 502

    # ✅ Add membership
    db.session.add(GroupMembership(group_id=grp.id, user_id=user.id, role="member"))
    db.session.commit()

    # 🔔 Notifications
    from notifications.utils import push_notification, push_to_many
    push_notification(user.id, f"✅ You joined {grp.name}", "success")
    admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
    if admin_ids:
        push_to_many(admin_ids, f"👥 {user.username} joined your group {grp.name}")

    return jsonify({
        "message": f"Joined {grp.name}",
        "group": {
            "name": grp.name,
            "slug": grp.slug,
            "cooperative_account_id": grp.cooperative_account_id,
            "members": count + 1,
            "rules": {
                "interest_rate": grp.interest_rate,
                "min_balance": grp.min_balance
            }
        }
    }), 200


@coop_bp.route("/<slug>", methods=["GET"])
@jwt_required()
def get_group(slug):
    """
    Get group details (basic).
    """
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    members = GroupMembership.query.filter_by(group_id=grp.id).all()
    out_members = []
    for m in members:
        ts = TrustScore.query.filter_by(user_id=m.user_id).first()
        out_members.append({
            "user_id": m.user_id,
            "role": m.role,
            "joined_at": m.joined_at.strftime("%Y-%m-%d %H:%M:%S"),
            "trust_score": ts.score if ts else None  # ✅ Add trust score from DB
        })

    return jsonify({
        "group": {
            "id": grp.id,  # ✅ Add this
            "name": grp.name,
            "slug": grp.slug,
            "cooperative_account_id": grp.cooperative_account_id,
            "created_by": grp.created_by,
            "created_at": grp.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "members": out_members,
            "dashboard_url": f"/group/{grp.slug}",
            "rules": {
                "interest_rate": grp.interest_rate,
                "min_balance": grp.min_balance
            }
        }
    }), 200


@coop_bp.route("/<slug>/balance", methods=["GET"])
@jwt_required()
def group_balance(slug):
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    try:
        bal = fetch_wallet_balance(grp.cooperative_account_id)

        # --- BHC token display ---
        bhc_token_id = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
        bhc_decimals = int(os.getenv("BHC_DECIMALS", "2"))

        bhc_raw = bal.get("token_balances", {}).get(bhc_token_id)
        bhc_display = None
        if bhc_raw is not None:
            bhc_display = float(bhc_raw) / (10 ** bhc_decimals)

        bal["bhc"] = {
            "token_id": bhc_token_id,
            "raw": bhc_raw,
            "display": bhc_display
        }

        return jsonify(bal), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@coop_bp.route("/<slug>/admin/reconcile", methods=["POST"])
@jwt_required()
def admin_reconcile_vault(slug):
    """
    Admin-only: On-chain BHC vault balance ko DB ledger ke saath reconcile karta hai.
    Logic:
      onchain = fetch_wallet_balance(vault).bhc_display
      inflows  = sum(ledger.amount where ref_type in ["deposit","repayment"])
      outflows = sum(ledger.amount where ref_type in ["withdraw","loan_disbursal","refund"])
      expected_vault = inflows - outflows
      delta = onchain - expected_vault
    If |delta| > epsilon -> TransactionLedger me 'reconcile_adjustment' entry add karta hai (user_id=None).
    NOTE: Ye member balances ko direct touch nahi karta; sirf ledger parity ensure karta hai.
    """
    uid = get_jwt_identity()
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    # admin check
    if not GroupMembership.query.filter_by(group_id=grp.id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can run reconciliation"}), 403

    # 1) On-chain vault balance
    try:
        bal = fetch_wallet_balance(grp.cooperative_account_id) or {}
        onchain_bhc = _bhc_display_from_balance_dict(bal)
    except Exception as e:
        return jsonify({"error": f"Failed to fetch on-chain balance: {e}"}), 502

    # 2) DB expected vault via ledger
    IN_TYPES = ["deposit", "repayment"]
    OUT_TYPES = ["withdraw", "loan_disbursal", "refund"]

    inflows = db.session.query(db.func.coalesce(db.func.sum(TransactionLedger.amount), 0.0)) \
                  .filter(TransactionLedger.group_id == grp.id,
                          TransactionLedger.ref_type.in_(IN_TYPES)).scalar() or 0.0

    outflows = db.session.query(db.func.coalesce(db.func.sum(TransactionLedger.amount), 0.0)) \
                   .filter(TransactionLedger.group_id == grp.id,
                           TransactionLedger.ref_type.in_(OUT_TYPES)).scalar() or 0.0

    expected_vault = float(inflows) - float(outflows)

    # 3) Delta & epsilon
    delta = round(onchain_bhc - expected_vault, 2)
    epsilon = 0.01  # 1 cent worth at 2 decimals

    result = {
        "group": {"id": grp.id, "slug": grp.slug, "name": grp.name},
        "onchain_bhc": float(onchain_bhc),
        "db_expected_vault": float(expected_vault),
        "delta": float(delta),
        "action": "none"
    }

    if abs(delta) <= epsilon:
        # Already in sync
        return jsonify({**result, "message": "✅ Vault looks in sync (within epsilon)."}), 200

    # 4) Record a reconciliation adjustment entry in ledger
    try:
        note = (f"Reconciliation adjustment. onchain={onchain_bhc}, "
                f"expected={expected_vault}, delta={delta}. "
                f"IN={inflows} OUT={outflows}")

        adj = TransactionLedger(
            group_id=grp.id,
            user_id=None,
            ref_type="reconcile_adjustment",
            ref_id=None,
            amount=abs(delta),  # amount always positive; sign explained in note
            note=(note + (" | DB<onchain so +adjust" if delta > 0 else " | DB>onchain so -adjust"))
        )
        db.session.add(adj)
        db.session.commit()

        result["action"] = "ledger_adjustment_recorded"
        return jsonify({**result, "message": "⚖️ Reconciliation ledger adjustment recorded."}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to record reconciliation", "detail": str(e), **result}), 500


@coop_bp.route("/<slug>/balances", methods=["GET"])
@jwt_required()
def group_balances(slug):
    uid = get_jwt_identity()
    user = User.query.get(uid)

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403

    from cooperative.models import MemberBalance

    rows = []
    if membership.role == "admin":
        # ✅ Admin → sabke balances
        balances = MemberBalance.query.filter_by(group_id=grp.id).all()
        for b in balances:
            net = float(b.total_deposit or 0) + float(b.interest_earned or 0) - float(b.total_withdrawn or 0)
            rows.append({
                "user_id": b.user_id,
                "total_deposit": float(b.total_deposit or 0),
                "interest_earned": float(b.interest_earned or 0),
                "total_withdrawn": float(b.total_withdrawn or 0),
                "net_balance": net
            })
    else:
        # ✅ Member → sirf apna
        mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=uid).first()
        if mb:
            net = float(mb.total_deposit or 0) + float(mb.interest_earned or 0) - float(mb.total_withdrawn or 0)
            rows.append({
                "user_id": uid,
                "total_deposit": float(mb.total_deposit or 0),
                "interest_earned": float(mb.interest_earned or 0),
                "total_withdrawn": float(mb.total_withdrawn or 0),
                "net_balance": net
            })

    return jsonify(rows), 200


@coop_bp.route("/<slug>/mybalance", methods=["GET"])
@jwt_required()
def my_balance(slug):
    uid = get_jwt_identity()
    user = User.query.get(uid)

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    from cooperative.models import MemberBalance
    mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not mb:
        return jsonify({"message": "No balance found"}), 200

    net = float(mb.total_deposit or 0) + float(mb.interest_earned or 0) - float(mb.total_withdrawn or 0)
    return jsonify({
        "user_id": uid,
        "total_deposit": float(mb.total_deposit or 0),
        "interest_earned": float(mb.interest_earned or 0),
        "total_withdrawn": float(mb.total_withdrawn or 0),
        "net_balance": net
    }), 200


# -------- WITHDRAW (on-chain BHC transfer + DB) --------
@coop_bp.route("/<slug>/withdraw", methods=["POST"])
@jwt_required()
def withdraw_from_group(slug):
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user or not user.hedera_account_id or not user.hedera_private_key:
        return jsonify({"error": "User Hedera wallet missing"}), 400

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp or not grp.cooperative_account_id:
        return jsonify({"error": "Group not found or missing vault account"}), 404

    mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not mb or (float(mb.total_deposit or 0) <= 0):
        return jsonify({"error": "No deposit found to withdraw"}), 400

    data = request.get_json() or {}
    try:
        amt = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid withdrawal amount"}), 400

    if amt <= 0 or amt > float(mb.total_deposit or 0):
        return jsonify({"error": "Invalid withdrawal amount"}), 400

    # Loan activity check (no profit -> no interest paid)
    active_loans = Loan.query.filter_by(group_id=grp.id, status="active").count()
    total_repaid = (Repayment.query
                    .join(Loan, Repayment.loan_id == Loan.id)
                    .filter(Loan.group_id == grp.id)
                    .count())

    interest = 0.0
    if active_loans > 0 or total_repaid > 0:
        interest_rate = float(grp.interest_rate or 0.10)
        # simple half-year interest model retained
        interest = amt * (interest_rate / 2)

    # Determine whether interest should be paid now or moved to profit pool
    distribute_on_profit = bool(getattr(grp, "distribute_on_profit", False))

    if distribute_on_profit and interest > 0:
        # user gets only principal now; interest goes to GroupProfitPool
        payout = amt
    else:
        # default / legacy: pay principal + interest now
        payout = amt + interest

    # On-chain transfer: group vault -> user
    try:
        tx = transfer_hts_token(
            token_id=BHC_TOKEN_ID,
            from_account=grp.cooperative_account_id,
            from_privkey=grp.hedera_private_key,
            to_account=user.hedera_account_id,
            amount=int(payout * (10 ** BHC_DECIMALS))
        )
    except Exception as e:
        return jsonify({"error": f"On-chain transfer failed: {str(e)}"}), 502

    # Validate SDK response best-effort
    if isinstance(tx, dict) and tx.get("status") and tx.get("status") != "SUCCESS":
        return jsonify({"error": "On-chain transfer did not return success", "tx": tx}), 502

    # DB updates
    try:
        # reduce deposit
        mb.total_deposit = float(mb.total_deposit or 0) - amt
        # if interest paid now -> credit member interest_earned
        if not distribute_on_profit and interest > 0:
            mb.interest_earned = float(mb.interest_earned or 0) + interest
            mb.total_withdrawn = float(mb.total_withdrawn or 0) + payout
        else:
            # interest parked in pool; user withdrawn only principal
            mb.total_withdrawn = float(mb.total_withdrawn or 0) + payout

        db.session.add(mb)

        # ledger: withdrawal entry
        db.session.add(TransactionLedger(
            group_id=grp.id, user_id=uid, ref_type="withdraw",
            ref_id=None, amount=payout,
            note=f"User withdraw principal {amt} (interest_handled={'pool' if distribute_on_profit and interest > 0 else 'paid'})"
        ))

        # If interest should be moved to group's profit pool, update/create pool
        if distribute_on_profit and interest > 0:
            from cooperative.models import GroupProfitPool
            pool = GroupProfitPool.query.filter_by(group_id=grp.id).first()
            now = datetime.utcnow()
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

            # ledger entry to record profit accrual
            db.session.add(TransactionLedger(
                group_id=grp.id, user_id=uid, ref_type="profit_accrual",
                ref_id=None, amount=interest,
                note=f"Interest {interest} parked to GroupProfitPool from withdraw by user {uid}"
            ))

        db.session.commit()
    except Exception as db_exc:
        db.session.rollback()

        # mark for manual reconcile instead of sending another transfer
        db.session.add(TransactionLedger(
            group_id=grp.id,
            user_id=uid,
            ref_type="refund_required",
            ref_id=None,
            amount=payout,
            note=f"Withdraw on-chain succeeded but DB commit failed. tx={tx}; err={db_exc}"
        ))
        db.session.commit()  # best-effort

        try:
            push_notification(uid, "⚠️ Withdraw DB failure. Marked REFUND_REQUIRED for admin reconcile.", "warning")
        except Exception:
            pass

        return jsonify({
            "error": "Withdraw succeeded on-chain but failed to record in DB. Admin reconciliation needed.",
            "db_error": str(db_exc),
            "onchain_tx": tx
        }), 500

    # notifications: push only (no create_notification)
    try:
        if distribute_on_profit and interest > 0:
            msg = f"🏦 You withdrew {amt} BHC. Interest {interest:.2f} BHC has been parked to group profit pool for future distribution."
            try:
                push_notification(uid, msg, "info")
            except Exception:
                pass

            # optionally notify admins about pool accrual
            try:
                admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
                if admin_ids:
                    try:
                        push_to_many(admin_ids, f"📈 {interest:.2f} BHC added to profit pool for {grp.name}.")
                    except Exception:
                        pass
            except Exception:
                pass
        else:
            msg = f"🏦 You withdrew {amt} BHC + {interest:.2f} interest = {payout:.2f} BHC"
            try:
                push_notification(uid, msg, "success")
            except Exception:
                pass
    except Exception:
        # swallow notification errors
        pass

    # notify admins about withdrawal (always, best-effort)
    try:
        admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
        if admin_ids:
            try:
                push_to_many(admin_ids, f"💸 {user.username} withdrew {amt} BHC from {grp.name}")
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({"message": msg, "tx": tx}), 201


# -------- DEPOSIT (on-chain BHC transfer + DB) --------
@coop_bp.route("/<slug>/deposit", methods=["POST"])
@jwt_required()
def deposit_to_group(slug):
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user or not user.hedera_account_id or not user.hedera_private_key:
        return jsonify({"error": "User Hedera wallet missing"}), 400
    if user.kyc_status != "verified":
        return jsonify({"error": "KYC required"}), 403

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp or not grp.cooperative_account_id:
        return jsonify({"error": "Group not found or missing vault account"}), 404

    is_member = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not is_member:
        return jsonify({"error": "Only group members can deposit"}), 403

    data = request.get_json() or {}
    try:
        amt = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    if amt <= 0:
        return jsonify({"error": "Invalid amount"}), 400

    # token config (safe defaults)
    BHC_TOKEN_ID = os.getenv("BHC_TOKEN_ID", "0.0.6625811")
    BHC_DECIMALS = int(os.getenv("BHC_DECIMALS", "2"))

    # 🔹 On-chain BHC transfer: user → group vault
    try:
        tx = transfer_hts_token(
            token_id=BHC_TOKEN_ID,
            from_account=user.hedera_account_id,
            from_privkey=user.hedera_private_key,
            to_account=grp.cooperative_account_id,
            amount=int(amt * (10 ** BHC_DECIMALS))
        )
    except Exception as e:
        return jsonify({"error": f"On-chain transfer failed: {str(e)}"}), 502

    # SDK quick check (best-effort)
    if isinstance(tx, dict) and tx.get("status") and tx.get("status") != "SUCCESS":
        return jsonify({"error": "On-chain transfer did not return success", "tx": tx}), 502

    # 🔹 DB ledger (commit; if it fails, try refund)
    try:
        dep = Deposit(group_id=grp.id, user_id=uid, amount=amt)
        db.session.add(dep)
        db.session.flush()

        mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=uid).first()
        if not mb:
            mb = MemberBalance(group_id=grp.id, user_id=uid, total_deposit=amt)
            db.session.add(mb)
        else:
            mb.total_deposit = (mb.total_deposit or 0) + amt
            db.session.add(mb)

        db.session.add(TransactionLedger(
            group_id=grp.id, user_id=uid, ref_type="deposit",
            ref_id=dep.id, amount=amt, note="User deposit"
        ))

        db.session.commit()

    except Exception as db_exc:
        db.session.rollback()

        # mark for manual reconcile instead of sending another transfer
        db.session.add(TransactionLedger(
            group_id=grp.id,
            user_id=uid,
            ref_type="refund_required",
            ref_id=None,
            amount=amt,
            note=f"Deposit on-chain succeeded but DB commit failed. tx={tx}; err={db_exc}"
        ))
        db.session.commit()  # best-effort

        try:
            push_notification(uid, "⚠️ Deposit DB failure. Marked REFUND_REQUIRED for admin reconcile.", "warning")
        except Exception:
            pass

        return jsonify({
            "error": "Deposit succeeded on-chain but failed to record in DB. Admin reconciliation needed.",
            "db_error": str(db_exc),
            "onchain_tx": tx
        }), 500

    # 🔹 Minimum balance enforcement (notify via push)
    if getattr(grp, "min_balance", None) and (mb.total_deposit or 0) < float(grp.min_balance):
        msg = f"⚠️ Minimum balance for {grp.name} is {grp.min_balance} BHC. You still need {(grp.min_balance - mb.total_deposit):.2f} BHC."
        try:
            push_notification(uid, msg, "warning")
        except Exception:
            pass
        return jsonify({"message": msg, "tx": tx}), 200

    # 🔔 Notifications (push only)
    try:
        push_notification(uid, f"✅ You deposited {amt} BHC into {grp.name}", "success")
    except Exception:
        pass

    try:
        admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
        if admin_ids:
            try:
                push_to_many(admin_ids, f"💰 {user.username} deposited {amt} BHC into {grp.name}")
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({"message": f"✅ {amt} BHC deposited into {grp.name}", "tx": tx}), 201


# -------- GET DEPOSITS (restricted by role) --------
@coop_bp.route("/<slug>/deposits", methods=["GET"])
@jwt_required()
def get_deposits(slug):
    uid = get_jwt_identity()
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403

    query = Deposit.query.filter_by(group_id=grp.id)

    # ✅ Admin → sabke deposits, Member → sirf apna
    if membership.role != "admin":
        query = query.filter_by(user_id=uid)

    deposits = query.all()
    out = []
    for d in deposits:
        out.append({
            "user_id": d.user_id,
            "amount": float(d.amount),
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    return jsonify(out), 200


# -------- LOAN REQUEST (+ auto VotingSession) --------
@coop_bp.route("/<slug>/loan", methods=["POST"])
@jwt_required()
def request_loan(slug):
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user or not user.hedera_account_id:
        return jsonify({"error": "User wallet missing"}), 400
    if user.kyc_status != "verified":
        return jsonify({"error": "KYC required"}), 403

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    is_member = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not is_member:
        return jsonify({"error": "Only group members can request loan"}), 403

    data = request.get_json() or {}
    try:
        amt = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid loan amount"}), 400
    if amt <= 0:
        return jsonify({"error": "Invalid loan amount"}), 400
    purpose = (data.get("purpose") or "").strip()

    # create loan request + voting session
    loan_req = LoanRequest(group_id=grp.id, user_id=uid, amount=amt, purpose=purpose, status="pending")
    db.session.add(loan_req)
    db.session.flush()

    vs = VotingSession(group_id=grp.id, loan_request_id=loan_req.id, status="ongoing")
    db.session.add(vs)
    db.session.commit()

    # notify all group members to vote (except requester)
    try:
        from notifications.utils import push_to_many, push_notification
        member_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id).all() if m.user_id != uid]
        if member_ids:
            push_to_many(member_ids,
                         f"🗳️ New loan request #{loan_req.id} in {grp.name}: {amt} BHC — Vote: vote {loan_req.id} yes|no")
    except Exception as e:
        # non-fatal: log/print for debug but do not block response
        print("⚠️ notify-members failed:", e)

    # acknowledgement to requester (push)
    try:
        push_notification(uid, f"📌 Loan request {amt} BHC created in {grp.name}", "info")
    except Exception:
        pass

    return jsonify({
        "message": f"📌 Loan request {amt} created, voting started",
        "loan_request_id": loan_req.id,
        "voting_session_id": vs.id
    }), 201


# ---------- LIST LOAN REQUESTS ----------
@coop_bp.route("/<slug>/loans", methods=["GET"])
@jwt_required()
def list_loans(slug):
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp: return jsonify({"error": "Group not found"}), 404
    rows = LoanRequest.query.filter_by(group_id=grp.id).order_by(LoanRequest.created_at.desc()).all()
    out = [{
        "id": r.id,
        "user_id": r.user_id,
        "amount": float(r.amount),
        "status": r.status,
        "purpose": r.purpose,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for r in rows]
    return jsonify(out), 200

# ---------- /loans/with-repayments (role-scoped) ----------
@coop_bp.route("/<slug>/loans/with-repayments", methods=["GET"])
@jwt_required()
def loans_with_repayments(slug):
    uid = get_jwt_identity()

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    # must be a member
    membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403

    # optional user filter (admin only)
    target_user_id = request.args.get("user_id", type=int)

    # base query
    q = Loan.query.filter_by(group_id=grp.id)
    if target_user_id:
        q = q.filter(Loan.user_id == target_user_id)

    loans = q.order_by(Loan.created_at.asc()).all()

    out = []
    for loan in loans:
        total_repaid = (
            db.session.query(db.func.coalesce(db.func.sum(Repayment.amount), 0.0))
            .filter(Repayment.loan_id == loan.id)
            .scalar()
        )
        outstanding = float(loan.principal) - float(total_repaid)
        if outstanding < 0:
            outstanding = 0.0

        out.append({
            "loan_id": loan.id,
            "user_id": loan.user_id,
            "principal": float(loan.principal),
            "repaid": float(total_repaid),
            "outstanding": float(outstanding),
            "created_at": loan.created_at.strftime("%Y-%m-%d"),
        })

    return jsonify(out), 200


# -------- VOTE (no disbursal here) --------
@coop_bp.route("/loan/<int:loan_request_id>/vote", methods=["POST"])
@jwt_required()
def vote_on_loan(loan_request_id):
    uid = get_jwt_identity()
    choice = (request.get_json() or {}).get("vote", "").lower()
    if choice not in {"yes", "no"}:
        return jsonify({"error": "Vote must be yes/no"}), 400

    session_obj = VotingSession.query.filter_by(
        loan_request_id=loan_request_id, status="ongoing"
    ).first()
    if not session_obj:
        return jsonify({"error": "No ongoing voting"}), 404

    if not GroupMembership.query.filter_by(
            group_id=session_obj.group_id, user_id=uid
    ).first():
        return jsonify({"error": "Only group members can vote"}), 403

    if VoteDetail.query.filter_by(session_id=session_obj.id, voter_id=uid).first():
        return jsonify({"message": "Already voted"}), 200

    db.session.add(VoteDetail(session_id=session_obj.id, voter_id=uid, choice=choice))
    db.session.commit()

    result = _close_voting_if_quorum(session_obj)
    if result["closed"]:
        lr = LoanRequest.query.get(loan_request_id)
        if lr:
            # set loan_request status (approved/rejected)
            lr.status = "approved" if result["approved"] else "rejected"
            db.session.add(lr)

            # If approved -> create a Loan record (status = "approved") idempotently
            created_loan = None
            if result["approved"]:
                existing_loan = Loan.query.filter_by(loan_request_id=lr.id).first()
                if not existing_loan:
                    interest_rate = float(CooperativeGroup.query.get(lr.group_id).interest_rate or 0.10)
                    if interest_rate > 1:
                        interest_rate = interest_rate / 100.0
                    monthly_interest = float(lr.amount) * interest_rate / 12.0
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
                    created_loan = loan
                else:
                    created_loan = existing_loan

            db.session.commit()

            # Notify group admins to disburse if approved
            if result["approved"]:
                try:
                    grp = CooperativeGroup.query.get(lr.group_id)
                    admin_ids = [m.user_id for m in
                                 GroupMembership.query.filter_by(group_id=lr.group_id, role="admin").all()]
                    if admin_ids:
                        from notifications.utils import push_to_many
                        push_to_many(admin_ids, f"🔔 Loan #{lr.id} approved for {grp.name}. Use: disburse {lr.id}")
                except Exception:
                    # swallow notification errors so voting flow stays stable
                    pass

            return jsonify({"message": f"Loan {lr.status}"}), 200

    return jsonify({"message": f"Vote recorded: {choice}"}), 200


# ---------- LIST VOTES (per request) ----------
@coop_bp.route("/<slug>/votes", methods=["GET"])
@jwt_required()
def list_votes(slug):
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp: return jsonify({"error": "Group not found"}), 404
    sessions = VotingSession.query.filter_by(group_id=grp.id).all()
    out = []
    for s in sessions:
        yes = VoteDetail.query.filter_by(session_id=s.id, choice="yes").count()
        no = VoteDetail.query.filter_by(session_id=s.id, choice="no").count()
        out.append({
            "loan_request_id": s.loan_request_id,
            "yes": yes, "no": no, "status": s.status
        })
    return jsonify(out), 200


# -------- LOAN DISBURSAL (after approval) --------
@coop_bp.route("/loan/<int:loan_request_id>/disburse", methods=["POST"])
@jwt_required()
def disburse_loan(loan_request_id):
    uid = get_jwt_identity()

    lr = LoanRequest.query.get(loan_request_id)
    if not lr:
        return jsonify({"error": "Loan request not found"}), 404
    if lr.status not in {"approved", "disbursed"}:
        return jsonify({"error": "Loan request not approved"}), 400

    grp = CooperativeGroup.query.get(lr.group_id)
    borrower = User.query.get(lr.user_id)
    if not grp or not borrower or not borrower.hedera_account_id:
        return jsonify({"error": "Invalid borrower or group"}), 404

    membership = GroupMembership.query.filter_by(
        group_id=grp.id, user_id=uid, role="admin"
    ).first()
    if not membership:
        return jsonify({"error": "Only this group's admin can disburse loans"}), 403

    # find Loan created at approval time
    loan = Loan.query.filter_by(loan_request_id=lr.id).first()
    if not loan:
        return jsonify(
            {"error": "Loan record not found. Voting-approved loans should create a Loan entry automatically."}), 400

    # idempotency: already active (disbursed)
    if loan.status == "active":
        return jsonify({"message": "Loan already disbursed", "loan_id": loan.id}), 200

    # Only allow disbursal when loan.status == "approved"
    if loan.status != "approved":
        return jsonify({"error": f"Loan in unexpected state: {loan.status}"}), 400

    # 4) On-chain transfer (vault → borrower)
    try:
        tx = transfer_hts_token(
            token_id=BHC_TOKEN_ID,
            from_account=grp.cooperative_account_id,
            from_privkey=grp.hedera_private_key,
            to_account=borrower.hedera_account_id,
            amount=int(float(lr.amount) * (10 ** BHC_DECIMALS))
        )
    except Exception as e:
        return jsonify({"error": f"On-chain transfer failed: {str(e)}"}), 502

    # Quick SDK success check (best-effort)
    if isinstance(tx, dict) and tx.get("status") and tx.get("status") != "SUCCESS":
        # Treat as transfer failure
        return jsonify({"error": "On-chain transfer did not return success", "tx": tx}), 502

    # 5) Activate loan and set disbursed timestamp
    loan.status = "active"
    loan.disbursed_at = datetime.utcnow()
    db.session.add(loan)
    db.session.flush()

    # 6) Repayment schedule (simple equal monthly amount)
    interest_rate = float(grp.interest_rate or 0.10)
    tenure = int(loan.tenure_months or 12)
    monthly_interest = (float(lr.amount) * interest_rate) / 12.0
    monthly_principal = float(lr.amount) / max(1, tenure)
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

    # 7) Update request + ledger
    lr.status = "disbursed"
    db.session.add(TransactionLedger(
        group_id=grp.id,
        user_id=lr.user_id,
        ref_type="loan_disbursal",
        ref_id=loan.id,
        amount=float(lr.amount),
        note=f"Loan disbursed {float(lr.amount)} BHC"
    ))

    # commit with safety: if DB fails after on-chain transfer, attempt refund
    try:
        db.session.commit()

    except Exception as db_exc:
        db.session.rollback()

        # mark for manual reconcile instead of sending another transfer
        db.session.add(TransactionLedger(
            group_id=grp.id,
            user_id=borrower.id,
            ref_type="refund_required",
            ref_id=loan.id,
            amount=float(lr.amount),
            note=f"Disbursal on-chain succeeded but DB commit failed. tx={tx}; err={db_exc}"
        ))
        db.session.commit()  # best-effort to record the flag

        try:
            push_notification(uid, "⚠️ Disbursal DB failure. Marked REFUND_REQUIRED for admin reconcile.", "warning")
            push_notification(borrower.id,
                              "⚠️ Your loan disbursal hit an internal error. Admins will reconcile.",
                              "warning")
        except Exception:
            pass

        return jsonify({
            "error": "Disbursal succeeded on-chain but failed to record in DB. Admin reconciliation needed.",
            "db_error": str(db_exc),
            "onchain_tx": tx
        }), 500


    # notifications on success (use only push_notification / push_to_many)
    try:
        push_notification(borrower.id, f"✅ Your loan #{loan.id} of {loan.principal} BHC has been disbursed.", "success")
        push_notification(uid, f"📤 You disbursed loan #{loan.id} to {borrower.username} ({loan.principal} BHC).",
                          "info")
        admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
        if admin_ids:
            push_to_many(admin_ids, f"📢 Loan #{loan.id} disbursed to {borrower.username} ({loan.principal} BHC)")
    except Exception:
        pass

    # audit + consensus publish for success (non-notification helpers kept as-is)
    try:
        log_audit_action(
            user_id=uid,
            action="Loan Disbursed",
            table_name="Loan",
            record_id=loan.id,
            old={},
            new={"status": loan.status, "disbursed_at": loan.disbursed_at.isoformat(), "onchain_tx": str(tx)}
        )
        consensus_publish({"action": "DISBURSE", "loan_id": loan.id, "tx": tx, "by": uid})
    except Exception:
        pass

    return jsonify({"message": f"Loan disbursed to {borrower.username}", "loan_id": loan.id, "tx": tx}), 200


# -------- ALERTS (list + auto-generate) --------
@coop_bp.route("/<slug>/alerts", methods=["GET"])
@jwt_required()
def get_alerts(slug):
    uid = get_jwt_identity()

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    alerts = Alert.query.filter_by(user_id=uid).order_by(Alert.created_at.desc()).all()
    out = []

    for a in alerts:
        out.append({
            "id": a.id,
            "message": a.message,
            "level": a.level,
            "created_at": a.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })

    # 🔹 Auto-generate runtime alerts (overdue repayment etc.)
    # 1) Check overdue installments
    overdue = RepaymentSchedule.query.join(Loan, RepaymentSchedule.loan_id == Loan.id) \
        .filter(
        Loan.group_id == grp.id,
        Loan.user_id == uid,
        RepaymentSchedule.status == "due",
        RepaymentSchedule.due_date < datetime.utcnow()
    ).all()

    for r in overdue:
        out.append({
            "id": f"overdue-{r.id}",
            "message": f"⚠️ Overdue installment #{r.installment_no} for Loan {r.loan_id}",
            "level": "warning",
            "created_at": r.due_date.strftime("%Y-%m-%d %H:%M:%S")
        })

    # 2) Check trust score
    ts = TrustScore.query.filter_by(user_id=uid).first()
    if ts and ts.score < 30:
        out.append({
            "id": f"ts-{uid}",
            "message": f"❌ Low trust score ({ts.score}). Future loan requests may be blocked.",
            "level": "critical",
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        })

    # 3) Check min balance
    mb = MemberBalance.query.filter_by(group_id=grp.id, user_id=uid).first()
    if grp.min_balance and (not mb or mb.total_deposit < grp.min_balance):
        out.append({
            "id": f"mb-{uid}",
            "message": f"ℹ️ Your deposits are below the group minimum balance ({grp.min_balance} BHC).",
            "level": "info",
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        })

    return jsonify(out), 200


# -------- TRUST SCORE UPDATE --------
@coop_bp.route("/<int:user_id>/trustscore/update", methods=["POST"])
@jwt_required()
def trustscore_update_endpoint(user_id):
    """
    Update user's trust score based on activity.
    Body: { "delta": +5, "reason": "DEPOSIT", "group_id": <grp_id>, "ref_table": "deposits", "ref_id": <id> }
    """

    uid = get_jwt_identity()
    actor = User.query.get(uid)
    if not actor:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    delta = float(data.get("delta", 0))
    reason = (data.get("reason") or "").upper()
    group_id = data.get("group_id")
    ref_table = data.get("ref_table")
    ref_id = data.get("ref_id")

    # 🔹 Fetch existing score
    ts = TrustScore.query.filter_by(user_id=user_id).first()
    if not ts:
        ts = TrustScore(user_id=user_id, score=0.0)
        db.session.add(ts)

    # 🔹 Update score
    ts.score = (ts.score or 0) + delta
    db.session.add(ts)

    # 🔹 History record
    hist = TrustScoreHistory(
        user_id=user_id,
        group_id=group_id,
        delta=delta,
        score_after=ts.score,
        reason=reason,
        ref_table=ref_table,
        ref_id=ref_id
    )
    db.session.add(hist)

    db.session.commit()

    # --- emit on-chain event (best-effort, non-blocking) ---
    try:
        contract_addr = os.getenv("COOPTRUST_CONTRACT")
        if contract_addr:
            score_x100 = int(round((float(ts.score or 0)) * 100))
            receipt = emit_trust_score(contract_addr, user_id, group_id or 0, score_x100, reason or "")
            if receipt and "txHash" in receipt:
                hist.onchain_tx = receipt["txHash"]
                db.session.commit()
            print(f"✅ On-chain TrustScore event emitted for user={user_id}, group={group_id}, score={ts.score}")
        else:
            print("⚠️ COOPTRUST_CONTRACT not set; skipping on-chain emit")
    except Exception as e:
        print("⚠️ emit_trust_score failed:", e)

    # 🔔 Push notification
    try:
        push_notification(user_id, f"📊 Trust Score updated: {ts.score:.2f} ({reason})", "info")
    except Exception:
        pass

    return jsonify({
        "message": f"Trust score updated to {ts.score}",
        "score": float(ts.score),
        "reason": reason
    }), 200


# ---------- LIST REPAYMENTS (role-scoped + ledger fallback) ----------
@coop_bp.route("/<slug>/repayments", methods=["GET"])
@jwt_required()
def list_repayments(slug):
    uid = get_jwt_identity()

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403

    # NEW: optional target (admin-only)
    target_user_id = request.args.get("user_id", type=int)

    q = (Repayment.query
         .join(Loan, Repayment.loan_id == Loan.id)
         .filter(Loan.group_id == grp.id))

    if membership.role == "admin":
        if target_user_id:
            q = q.filter(Repayment.payer_id == target_user_id)
    else:
        q = q.filter(Repayment.payer_id == uid)

    rows = q.order_by(Repayment.created_at.desc()).all()
    out = [{
        "loan_id": r.loan_id,
        "payer_id": r.payer_id,
        "amount": float(r.amount),
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for r in rows]
    if out:
        return jsonify(out), 200

    # 🔁 Fallback: derive from ledger
    txq = TransactionLedger.query.filter_by(group_id=grp.id, ref_type="repayment")
    if membership.role == "admin":
        if target_user_id:
            txq = txq.filter_by(user_id=target_user_id)
    else:
        txq = txq.filter_by(user_id=uid)

    txrows = txq.order_by(TransactionLedger.created_at.desc()).all()
    fallback = [{
        "loan_id": None,
        "payer_id": t.user_id,
        "amount": float(t.amount),
        "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "ledger"
    } for t in txrows]
    return jsonify(fallback), 200



# ---------- LEDGER (role-scoped) ----------
@coop_bp.route("/<slug>/ledger", methods=["GET"])
@jwt_required()
def list_ledger(slug):
    uid = get_jwt_identity()

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403

    q = TransactionLedger.query.filter_by(group_id=grp.id)
    if membership.role != "admin":
        q = q.filter_by(user_id=uid)  # 🔒 members see only their own entries

    txs = q.order_by(TransactionLedger.created_at.desc()).all()
    out = [{
        "ref_type": t.ref_type,
        "user_id": t.user_id,
        "amount": float(t.amount),
        "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for t in txs]
    return jsonify(out), 200


# -------- REPAYMENT + DISTRIBUTION (auto pool credit only, safer) --------
@coop_bp.route("/loan/<int:loan_request_id>/repay", methods=["POST"])
@jwt_required()
def repay_loan(loan_request_id):
    uid = int(get_jwt_identity())
    user = User.query.get(uid)
    if not user or not user.hedera_account_id or not user.hedera_private_key:
        return jsonify({"error": "User Hedera wallet missing"}), 400

    loan = Loan.query.filter_by(loan_request_id=loan_request_id).first()
    if not loan or loan.status != "active":
        return jsonify({"error": "Loan not active or not found"}), 400

    grp = CooperativeGroup.query.get(loan.group_id)
    if not grp or not grp.cooperative_account_id:
        return jsonify({"error": "Group vault not found"}), 404

    data = request.get_json() or {}
    try:
        amt = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid repayment amount"}), 400
    if amt <= 0:
        return jsonify({"error": "Invalid repayment amount"}), 400

    try:
        # compute outstanding before applying this repayment
        total_repaid_before = sum(float(r.amount) for r in Repayment.query.filter_by(loan_id=loan.id).all())
        outstanding_before = max(0.0, float(loan.principal) - total_repaid_before)

        # record repayment row
        rep = Repayment(loan_id=loan.id, payer_id=uid, amount=amt)
        db.session.add(rep)
        db.session.flush()

        # ledger entry
        db.session.add(TransactionLedger(
            group_id=grp.id, user_id=uid, ref_type="repayment",
            ref_id=rep.id, amount=amt, note=f"Loan repayment {amt}"
        ))

        # borrower identity check
        lr = LoanRequest.query.get(loan_request_id)
        is_borrower = (uid == loan.user_id) or (lr and lr.user_id == uid)

        # -------- CASE A: third-party payer -> hold & require admin approval --------
        if not is_borrower:
            db.session.add(PaymentAudit(
                payment_id=rep.id, group_id=grp.id, loan_id=loan.id,
                payer_id=uid, borrower_id=loan.user_id, amount=amt,
                applied_amount=0, status="SUSPECT", reason="payer != borrower"
            ))
            db.session.add(PaymentApproval(
                repayment_id=rep.id, payer_id=uid,
                is_agent_payment=True, approved=False,
                notes="Third-party repayment pending admin approval"
            ))
            db.session.commit()

            try:
                push_notification(uid, f"🔔 Payment {amt} BHC received, pending admin approval.", "info")
            except Exception:
                pass
            try:
                push_notification(loan.user_id,
                                  f"🔔 A payment of {amt} BHC was received for your loan #{loan.id} and is waiting for admin approval.",
                                  "info")
            except Exception:
                pass
            try:
                admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
                if admin_ids:
                    push_to_many(admin_ids,
                                 f"🛎️ Third-party payment #{rep.id} for Loan #{loan.id} ({amt} BHC) awaiting your approval.")
            except Exception:
                pass

            return jsonify({"message": "Payment pending admin approval", "repayment_id": rep.id}), 202

        # -------- CASE B: borrower paying themselves -> auto-apply --------
        try:
            tx = transfer_hts_token(
                token_id=BHC_TOKEN_ID,
                from_account=user.hedera_account_id,
                from_privkey=user.hedera_private_key,
                to_account=grp.cooperative_account_id,
                amount=int(amt * (10 ** BHC_DECIMALS))
            )
        except Exception as e:
            return jsonify({"error": f"On-chain repayment failed: {str(e)}"}), 502

        if isinstance(tx, dict) and tx.get("status") and tx.get("status") != "SUCCESS":
            return jsonify({"error": "On-chain transfer did not return success", "tx": tx}), 502

        to_apply = min(amt, outstanding_before)
        excess = round(amt - to_apply, 2)

        # ---- 🔑 Installment update (main fix) ----
        remain = to_apply
        schedules = (RepaymentSchedule.query
                     .filter_by(loan_id=loan.id, status="due")
                     .order_by(RepaymentSchedule.installment_no.asc()).all())
        for s in schedules:
            if remain <= 0:
                break
            due_amt = float(getattr(s, "due_amount", 0) or 0)
            if remain + 1e-9 >= due_amt:
                s.status = "paid"
                s.paid_at = rep.created_at
                if hasattr(s, "paid_repayment_id"):
                    s.paid_repayment_id = rep.id
                remain -= due_amt
                db.session.add(s)
            else:
                break

        # audit log
        db.session.add(PaymentAudit(
            payment_id=rep.id, group_id=grp.id, loan_id=loan.id,
            payer_id=uid, borrower_id=loan.user_id,
            amount=amt, applied_amount=to_apply,
            status="OK", reason="normal repayment"
        ))
        # Profit pool
        interest_pool = 0.0
        if to_apply > 0:
            group_rate = float(grp.interest_rate or 0.0)
            # normalize: if stored as 12 (percent), convert to 0.12
            if group_rate > 1:
                group_rate = group_rate / 100.0

            interest_pool = to_apply * (group_rate / 2.0)

            gpp = GroupProfitPool.query.filter_by(group_id=grp.id).first()
            now = datetime.utcnow()
            if not gpp:
                gpp = GroupProfitPool(
                    group_id=grp.id,
                    accrued_interest=interest_pool,
                    expenses=0,
                    net_available=interest_pool,
                    created_at=now,
                    last_updated=now
                )
                db.session.add(gpp)
            else:
                gpp.accrued_interest = float(gpp.accrued_interest or 0) + interest_pool
                gpp.net_available = float(gpp.net_available or 0) + interest_pool
                gpp.last_updated = now
                db.session.add(gpp)

            db.session.add(TransactionLedger(
                group_id=grp.id, user_id=None, ref_type="profit_pool_credit",
                ref_id=rep.id, amount=interest_pool,
                note=f"Interest {interest_pool:.2f} from repayment {rep.id} → GroupProfitPool"
            ))


        # Excess → CreditLedger
        if excess > 0:
            cl = CreditLedger.query.filter_by(group_id=grp.id, user_id=uid).first()
            if not cl:
                cl = CreditLedger(group_id=grp.id, user_id=uid, amount=excess,
                                  source="OVERPAYMENT", note=f"Overpayment from repayment {rep.id}")
                db.session.add(cl)
            else:
                cl.amount = float(cl.amount or 0) + excess
            db.session.add(TransactionLedger(
                group_id=grp.id, user_id=uid, ref_type="credit_parked",
                ref_id=rep.id, amount=excess,
                note=f"Overpayment parked {excess} BHC from repayment {rep.id}"
            ))

        # Close loan if fully repaid
        if to_apply > 0:
            total_after = total_repaid_before + to_apply
            if total_after >= float(loan.principal):
                loan.status = "closed"
                loan.closed_at = datetime.utcnow()
            db.session.add(loan)

        db.session.commit()

    except Exception as db_exc:
        db.session.rollback()
        try:
            push_notification(uid, "⚠️ Repayment processing failed (internal). Admin will reconcile.", "warning")
        except Exception:
            pass
        return jsonify({"error": "DB error during repayment", "detail": str(db_exc)}), 500

    msg = f"💵 Repayment {amt} BHC processed. Applied {to_apply}, Excess {excess}, Profit {interest_pool:.2f} added to pool for scheduled distribution."
    try:
        push_notification(uid, msg, "success")
    except Exception:
        pass

    return jsonify({"message": msg, "tx": tx}), 201


# -------- ADMIN APPROVAL --------
@coop_bp.route("/admin/payment/<int:repayment_id>/approve", methods=["POST"])
@jwt_required()
def admin_approve_payment(repayment_id):
    uid = int(get_jwt_identity())

    # fetch approval + audit
    approval = PaymentApproval.query.filter_by(repayment_id=repayment_id).first()
    if not approval:
        return jsonify({"error": "Approval record not found"}), 404

    audit = PaymentAudit.query.filter_by(payment_id=repayment_id).first()
    if not audit:
        return jsonify({"error": "Payment audit missing - manual reconcile needed"}), 404

    grp = CooperativeGroup.query.get(audit.group_id)
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    if not GroupMembership.query.filter_by(group_id=grp.id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can approve payments"}), 403

    # idempotency: already approved
    if approval.approved:
        return jsonify({"message": "Already approved", "repayment_id": repayment_id}), 200

    # parse optional apply_amount from admin request (how much to apply to loan)
    data = request.get_json() or {}
    try:
        apply_amount = None
        if "apply_amount" in data:
            apply_amount = float(data.get("apply_amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid apply_amount"}), 400

    try:
        rep = Repayment.query.get(repayment_id)
        if not rep:
            return jsonify({"error": "Repayment record missing"}), 404

        # determine amounts
        total_payment = float(audit.amount or 0)
        # default apply = full payment unless admin provided a specific amount
        if apply_amount is None:
            applied = round(total_payment, 2)
        else:
            applied = round(apply_amount, 2)

        if applied < 0 or applied > total_payment:
            return jsonify({"error": "apply_amount must be between 0 and the payment amount"}), 400

        excess = round(total_payment - applied, 2)

        # mark approval
        approval.approved = True
        approval.approved_at = datetime.utcnow()
        approval.approver_id = uid
        db.session.add(approval)

        # update audit applied_amount for recordkeeping
        audit.applied_amount = applied
        audit.status = "APPROVED"
        db.session.add(audit)

        # apply repayment portion (create ledger entry and update loan)
        if applied > 0:
            db.session.add(TransactionLedger(
                group_id=grp.id, user_id=rep.payer_id, ref_type="repayment_applied",
                ref_id=rep.id, amount=applied, note=f"Admin applied {applied} BHC"
            ))

            loan = Loan.query.get(audit.loan_id)
            if loan:
                # compute total repaid (including this repayment row which already exists)
                total_repaid = sum(float(r.amount) for r in Repayment.query.filter_by(loan_id=loan.id).all())
                # If your model expects applied portion to be recorded elsewhere, consider adjusting here.
                # We treat total_repaid >= principal -> close loan.
                if total_repaid >= float(loan.principal):
                    loan.status = "closed"
                    loan.closed_at = datetime.utcnow()
                db.session.add(loan)

        # handle excess → credit ledger (parked credit / savings)
        if excess > 0:
            cl = CreditLedger.query.filter_by(group_id=grp.id, user_id=rep.payer_id).first()
            if not cl:
                cl = CreditLedger(
                    group_id=grp.id, user_id=rep.payer_id, amount=excess,
                    source="OVERPAYMENT", note=f"Admin parked overpayment #{repayment_id}"
                )
                db.session.add(cl)
            else:
                cl.amount = (float(cl.amount or 0) + excess)
            db.session.add(TransactionLedger(
                group_id=grp.id, user_id=rep.payer_id, ref_type="credit_parked",
                ref_id=rep.id, amount=excess, note=f"Admin parked {excess} BHC"
            ))

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Approval failed", "detail": str(e)}), 500

    # notifications (best-effort)
    try:
        push_notification(rep.payer_id, f"✅ Your payment #{repayment_id} was approved by admin.", "success")
    except Exception:
        pass

    try:
        admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
        if admin_ids:
            push_to_many(admin_ids, f"📝 Payment #{repayment_id} approved by Admin {uid}")
    except Exception:
        pass

    return jsonify({"message": "Payment approved and applied", "repayment_id": repayment_id,
                    "applied": applied, "excess": excess}), 200


# ----- ADMIN: manage group profit pool -----  (READ-ONLY)
@coop_bp.route("/admin/group/<int:group_id>/profit/pool", methods=["GET"])
@jwt_required()
def admin_manage_profit_pool(group_id):
    """
    Admin-only (READ): return the group's profit pool snapshot.
    Note: this endpoint is intentionally read-only — admin cannot modify pool here.
    Pool creation / updates must be performed by system jobs (cron) or internal system-only endpoints.
    """
    from cooperative.models import GroupProfitPool, CooperativeGroup

    uid = get_jwt_identity()
    grp = CooperativeGroup.query.get(group_id)
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    # only group admins may view pool details
    if not GroupMembership.query.filter_by(group_id=group_id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can view profit pool"}), 403

    pool = GroupProfitPool.query.filter_by(group_id=group_id).first()
    if not pool:
        # return zeroed structure (do NOT create)
        return jsonify({
            "message": "Profit pool not initialized",
            "pool": {
                "group_id": group_id,
                "accrued_interest": 0.0,
                "expenses": 0.0,
                "net_available": 0.0,
                "last_updated": None
            }
        }), 200

    return jsonify({
        "pool": {
            "group_id": pool.group_id,
            "accrued_interest": float(pool.accrued_interest or 0),
            "expenses": float(pool.expenses or 0),
            "net_available": float(pool.net_available or 0),
            "last_updated": pool.last_updated.strftime("%Y-%m-%d %H:%M:%S") if pool.last_updated else None
        }
    }), 200


# ----- ADMIN: view profit distribution (READ-ONLY) -----
@coop_bp.route("/admin/group/<int:group_id>/profit/distribute", methods=["GET"])
@jwt_required()
def admin_view_profit_distribution(group_id):
    """
    Admin-only (READ): view distributable amounts and last distributions.
    Admins cannot trigger distribution here. System job must call /system/... endpoint.
    """
    from cooperative.models import GroupProfitPool, ProfitDistribution, ProfitShareDetail, CooperativeGroup, \
        MemberBalance
    uid = get_jwt_identity()

    grp = CooperativeGroup.query.get(group_id)
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    # admin check (view only)
    if not GroupMembership.query.filter_by(group_id=group_id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can view profit distribution data"}), 403

    pool = GroupProfitPool.query.filter_by(group_id=group_id).first()
    net = float(pool.net_available or 0) if pool else 0.0
    reserve_pct = float(getattr(grp, "profit_reserve_pct", 0) or 0)
    admin_pct = float(getattr(grp, "admin_cut_pct", 0) or 0)

    reserve_amt = round(net * (reserve_pct / 100.0), 2)
    admin_amt = round(net * (admin_pct / 100.0), 2)
    distributable = round(max(0.0, net - reserve_amt - admin_amt), 2)

    # last distributions (small sample)
    recent = ProfitDistribution.query.filter_by(group_id=group_id).order_by(
        ProfitDistribution.distributed_at.desc()).limit(10).all()
    recent_out = [{
        "id": r.id,
        "distributed_at": r.distributed_at.strftime("%Y-%m-%d %H:%M:%S"),
        "total_distributed": float(r.total_distributed or 0),
        "reserve_amount": float(r.reserve_amount or 0),
        "admin_amount": float(r.admin_amount or 0),
        "note": r.note
    } for r in recent]

    # basic deposit snapshot sanity
    members_bal = MemberBalance.query.filter_by(group_id=group_id).all()
    total_deposit = sum(float(m.total_deposit or 0) for m in members_bal) if members_bal else 0.0

    return jsonify({
        "group_id": group_id,
        "distribute_on_profit": bool(getattr(grp, "distribute_on_profit", True)),
        "pool_net_available": net,
        "reserve_pct": reserve_pct,
        "admin_pct": admin_pct,
        "reserve_amt": reserve_amt,
        "admin_amt": admin_amt,
        "distributable_if_run": distributable,
        "total_deposit_snapshot": total_deposit,
        "recent_distributions": recent_out
    }), 200


# ----- SYSTEM-ONLY: distribute profits (callable by cron / internal job) -----
@coop_bp.route("/system/group/<int:group_id>/profit/distribute", methods=["POST"])
def system_distribute_profit(group_id):
    """
    System-only endpoint to perform profit distribution.
    Protect this endpoint by setting SYSTEM_API_KEY env var and sending X-SYSTEM-KEY header.
    Body options (optional):
      { "force_distribute": true }  # only honored when valid SYSTEM key provided (i.e., this endpoint)
    This endpoint performs the same distribution logic but is intended to be invoked by cron / scheduler.
    """
    # system auth
    system_key = os.getenv("SYSTEM_API_KEY")
    provided = (request.headers.get("X-SYSTEM-KEY") or "")
    if not system_key or provided != system_key:
        return jsonify({"error": "Unauthorized - system key required"}), 401

    # local imports
    from cooperative.models import (GroupProfitPool, ProfitDistribution, ProfitShareDetail,
                                    CooperativeGroup, MemberBalance, TransactionLedger as TL)
    uid = None  # system actor (no JWT)

    grp = CooperativeGroup.query.get(group_id)
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    data = request.get_json() or {}
    force = bool(data.get("force_distribute", False))

    # respect group-level toggle unless forced (system may pass force=true)
    if not force and getattr(grp, "distribute_on_profit", None) is False:
        return jsonify({"message": "Group configured to not auto-distribute profits"}, 200)

    pool = GroupProfitPool.query.filter_by(group_id=group_id).first()
    if not pool or float(pool.net_available or 0) <= 0:
        return jsonify({"message": "No profits available to distribute"}), 200

    net = float(pool.net_available or 0)

    # read policy percentages
    reserve_pct = float(getattr(grp, "profit_reserve_pct", 0) or 0)  # percent, e.g., 10 -> 10%
    admin_pct = float(getattr(grp, "admin_cut_pct", 0) or 0)

    reserve_amt = round(net * (reserve_pct / 100.0), 2)
    admin_amt = round(net * (admin_pct / 100.0), 2)

    distributable = round(net - reserve_amt - admin_amt, 2)
    if distributable <= 0:
        return jsonify({
            "message": "After reserve/admin cut no distributable amount remains",
            "net": net,
            "reserve": reserve_amt,
            "admin_cut": admin_amt
        }), 200

    # snapshot member deposits
    members_bal = MemberBalance.query.filter_by(group_id=group_id).all()
    total_deposit = sum(float(m.total_deposit or 0) for m in members_bal) if members_bal else 0.0
    if total_deposit <= 0:
        return jsonify({"error": "No member deposits to distribute against; cannot distribute"}), 400

    now = datetime.utcnow()
    # create distribution record
    pd = ProfitDistribution(
        group_id=group_id,
        distributed_at=now,
        total_distributed=distributable,
        reserve_amount=reserve_amt,
        admin_amount=admin_amt,
        note=f"System distribution at {now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    db.session.add(pd)
    db.session.flush()  # to get pd.id

    per_user = []
    distributed_total_calc = 0.0

    # compute each share and persist
    for mb in members_bal:
        user_deposit = float(mb.total_deposit or 0)
        if user_deposit <= 0:
            share = 0.0
        else:
            share = round((user_deposit / total_deposit) * distributable, 2)

        per_user.append((mb, share))
        distributed_total_calc += share

    # fix rounding difference: adjust last non-zero depositor
    rounding_diff = round(distributable - distributed_total_calc, 2)
    if rounding_diff != 0:
        for mb, share in reversed(per_user):
            if float(mb.total_deposit or 0) > 0:
                idx = next(i for i, pair in enumerate(per_user) if pair[0].id == mb.id)
                per_user[idx] = (mb, round(per_user[idx][1] + rounding_diff, 2))
                distributed_total_calc = round(distributed_total_calc + rounding_diff, 2)
                break

    # persist share details and update member balances + ledger
    for mb, share in per_user:
        if share <= 0:
            continue

        psd = ProfitShareDetail(
            distribution_id=pd.id,
            user_id=mb.user_id,
            amount=share,
            deposit_snapshot=mb.total_deposit
        )
        db.session.add(psd)

        # credit member's interest_earned
        mb.interest_earned = (float(mb.interest_earned or 0) + float(share))
        try:
            if hasattr(mb, "last_profit_share_at"):
                mb.last_profit_share_at = now
        except Exception:
            pass
        db.session.add(mb)

        # ledger entry per user
        db.session.add(TL(
            group_id=group_id,
            user_id=mb.user_id,
            ref_type="profit_share",
            ref_id=pd.id,
            amount=float(share),
            note=f"Profit share {share} from distribution {pd.id}"
        ))

    # admin cut ledger (user_id null) and reserve ledger
    db.session.add(TL(
        group_id=group_id,
        user_id=None,
        ref_type="profit_reserve",
        ref_id=pd.id,
        amount=float(reserve_amt),
        note=f"Profit reserve {reserve_amt} from distribution {pd.id}"
    ))
    db.session.add(TL(
        group_id=group_id,
        user_id=None,
        ref_type="admin_cut",
        ref_id=pd.id,
        amount=float(admin_amt),
        note=f"Admin cut {admin_amt} from distribution {pd.id}"
    ))

    # update pool: consume net_available fully (or by consumed amounts)
    pool.net_available = round(float(pool.net_available or 0) - (reserve_amt + admin_amt + distributed_total_calc), 2)
    try:
        pool.accrued_interest = round(
            float(pool.accrued_interest or 0) - (distributed_total_calc + reserve_amt + admin_amt), 2)
        if pool.accrued_interest < 0:
            pool.accrued_interest = 0
    except Exception:
        pass
    pool.last_updated = now
    db.session.add(pool)

    try:
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to commit distribution", "detail": str(e)}), 500

    # notifications to admins (best-effort)
    try:
        admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=group_id, role="admin").all()]
        if admin_ids:
            from notifications.utils import push_to_many
            push_to_many(admin_ids,
                         f"📤 System profit distributed: {distributed_total_calc} BHC (reserve {reserve_amt}, admin {admin_amt})")
    except Exception:
        pass

    # response
    shares = [{"user_id": mb.user_id, "share": share, "deposit_snapshot": float(mb.total_deposit or 0)} for mb, share in
              per_user if share > 0]

    return jsonify({
        "message": "Profit distributed by system",
        "distribution_id": pd.id,
        "total_distributed": float(distributed_total_calc),
        "reserve": float(reserve_amt),
        "admin_cut": float(admin_amt),
        "shares_count": len(shares),
        "shares_sample": shares[:50],
    }), 200


# -------- ADMIN REJECT (refund or mark rejected) --------
@coop_bp.route("/admin/payment/<int:repayment_id>/reject", methods=["POST"])
@jwt_required()
def admin_reject_payment(repayment_id):
    uid = get_jwt_identity()

    approval = PaymentApproval.query.filter_by(repayment_id=repayment_id).first()
    audit = PaymentAudit.query.filter_by(payment_id=repayment_id).first()
    if not approval or not audit:
        return jsonify({"error": "Approval or audit record not found"}), 404

    grp = CooperativeGroup.query.get(audit.group_id)
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    if not GroupMembership.query.filter_by(group_id=grp.id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can reject payments"}), 403

    # Idempotent: already approved -> cannot reject
    if approval.approved:
        return jsonify({"error": "Payment already approved; cannot reject"}), 400

    # Try refunding the on-chain amount back to payer (best-effort)
    rep = Repayment.query.get(repayment_id)
    refund_msg = None
    refund_ok = False
    if rep:
        payer = User.query.get(rep.payer_id)
        payer_acct = getattr(payer, "hedera_account_id", None) if payer else None
        if payer_acct:
            try:
                refund_tx = transfer_hts_token(
                    token_id=BHC_TOKEN_ID,
                    from_account=grp.cooperative_account_id,
                    from_privkey=grp.hedera_private_key,
                    to_account=payer_acct,
                    amount=int(float(audit.amount) * (10 ** BHC_DECIMALS))
                )
                refund_msg = f"Refund attempted: {refund_tx}"
                refund_ok = True
                db.session.add(TransactionLedger(
                    group_id=grp.id, user_id=rep.payer_id, ref_type="refund",
                    ref_id=rep.id, amount=float(audit.amount), note=f"Admin refund for repayment {repayment_id}"
                ))
            except Exception as e:
                refund_msg = f"Refund failed: {str(e)}"
        else:
            refund_msg = "Refund skipped: payer Hedera account missing."

    # mark audit + approval (approved stays False)
    try:
        approval.approved = False
        approval.approved_at = datetime.utcnow()
        approval.approver_id = uid
        db.session.add(approval)

        audit.status = "REJECTED"
        audit.reason = (audit.reason or "") + " | rejected_by_admin"
        db.session.add(audit)

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to mark rejection", "detail": str(e)}), 500

    # notify payer + admins (use only push_notification / push_to_many)
    try:
        if rep:
            try:
                push_notification(rep.payer_id,
                                  f"❌ Your payment #{repayment_id} was rejected by admin. {('Refunded' if refund_ok else refund_msg or 'Refund failed or skipped')}",
                                  "warning")
            except Exception:
                pass

        admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
        if admin_ids:
            try:
                push_to_many(admin_ids,
                             f"🛑 Payment #{repayment_id} rejected by Admin {uid}. {refund_msg or ''}")
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({"message": "Payment rejected", "refund": refund_msg}), 200


# -------- ADMIN: list pending suspicious payments ----------
@coop_bp.route("/admin/payments/pending", methods=["GET"])
@jwt_required()
def admin_list_pending_payments():
    uid = get_jwt_identity()
    # returns all SUSPECT audits for groups where caller is admin
    admin_groups = [m.group_id for m in GroupMembership.query.filter_by(user_id=uid, role="admin").all()]
    if not admin_groups:
        return jsonify({"error": "Not an admin of any group"}), 403

    audits = PaymentAudit.query.filter(PaymentAudit.group_id.in_(admin_groups),
                                       PaymentAudit.status == 'SUSPECT').order_by(PaymentAudit.created_at.desc()).all()
    out = []
    for a in audits:
        out.append({
            "payment_id": a.payment_id,
            "audit_id": a.id,
            "group_id": a.group_id,
            "loan_id": a.loan_id,
            "payer_id": a.payer_id,
            "borrower_id": a.borrower_id,
            "amount": float(a.amount),
            "applied_amount": float(a.applied_amount or 0),
            "status": a.status,
            "reason": a.reason,
            "created_at": a.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    return jsonify(out), 200


# -------- ADMIN or USER: view credit ledger (scoped) ----------
@coop_bp.route("/admin/group/<int:group_id>/credits", methods=["GET"])
@jwt_required()
def admin_group_credits(group_id):
    uid = get_jwt_identity()
    # check membership
    membership = GroupMembership.query.filter_by(group_id=group_id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403

    # admin → see all rows
    if membership.role == "admin":
        rows = CreditLedger.query.filter_by(group_id=group_id).all()
    else:
        # non-admin → see only their own credits
        rows = CreditLedger.query.filter_by(group_id=group_id, user_id=uid).all()

    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "user_id": r.user_id,
            "loan_id": r.loan_id,
            "amount": float(r.amount),
            "source": r.source,
            "note": r.note,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    return jsonify(out), 200


# -------- ADMIN: apply parked credit to loan (manual admin action) ----------
@coop_bp.route("/admin/credit/<int:credit_id>/apply", methods=["POST"])
@jwt_required()
def admin_apply_credit(credit_id):
    uid = get_jwt_identity()
    data = request.get_json() or {}
    try:
        target_loan_id = int(data.get("loan_id"))
    except Exception:
        return jsonify({"error": "Invalid or missing loan_id"}), 400

    try:
        amount_to_apply = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    if amount_to_apply <= 0:
        return jsonify({"error": "Invalid apply amount"}), 400

    cl = CreditLedger.query.get(credit_id)
    if not cl:
        return jsonify({"error": "Credit record not found"}), 404

    grp = CooperativeGroup.query.get(cl.group_id)
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    if not GroupMembership.query.filter_by(group_id=grp.id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can apply credits"}), 403

    if amount_to_apply > float(cl.amount or 0):
        return jsonify({"error": "Apply amount exceeds parked credit balance"}), 400

    loan = Loan.query.get(target_loan_id)
    if not loan:
        return jsonify({"error": "Target loan not found"}), 404

    try:
        # create a Repayment record representing applied credit (payer is original credit owner)
        rep = Repayment(loan_id=loan.id, payer_id=cl.user_id, amount=amount_to_apply)
        db.session.add(rep)
        db.session.flush()  # ensure rep.id available for ledger

        # reduce credit ledger
        cl.amount = float(cl.amount or 0) - amount_to_apply
        db.session.add(cl)

        # ledger entry for applied credit
        db.session.add(TransactionLedger(
            group_id=grp.id,
            user_id=cl.user_id,
            ref_type="credit_applied",
            ref_id=rep.id,
            amount=amount_to_apply,
            note=f"Admin-applied credit {amount_to_apply} to loan {loan.id}"
        ))

        # compute total repaid and close loan if needed
        total_repaid = sum(float(r.amount) for r in Repayment.query.filter_by(loan_id=loan.id).all())
        if total_repaid >= float(loan.principal):
            loan.status = "closed"
            loan.closed_at = datetime.utcnow()
        db.session.add(loan)

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to apply credit", "detail": str(e)}), 500

    # notifications (use only push_notification / push_to_many)
    try:
        # notify credit owner
        try:
            push_notification(cl.user_id,
                              f"✅ {amount_to_apply} BHC of your parked credit was applied to Loan #{loan.id}.",
                              "success")
        except Exception:
            pass

        # notify group admins
        try:
            admin_ids = [m.user_id for m in GroupMembership.query.filter_by(group_id=grp.id, role="admin").all()]
            if admin_ids:
                push_to_many(admin_ids,
                             f"📌 Admin {uid} applied {amount_to_apply} BHC from credit #{cl.id} to Loan #{loan.id}.")
        except Exception:
            pass
    except Exception:
        pass

    return jsonify({"message": "Credit applied", "loan_id": loan.id, "applied": amount_to_apply}), 200


# ----- AUTO: scheduled profit settlement / distribute job -----
def auto_settle_and_distribute_profits():
    """
    System-only (cron/job):
    - Runs periodically (e.g., daily/weekly/monthly).
    - Iterates all groups with profit pools > 0.
    - Applies reserve/admin cut.
    - Distributes net profit automatically to members.
    """
    from cooperative.models import (
        CooperativeGroup, GroupProfitPool, MemberBalance,
        ProfitDistribution, ProfitShareDetail, TransactionLedger
    )
    now = datetime.utcnow()
    groups = CooperativeGroup.query.all()

    for grp in groups:
        pool = GroupProfitPool.query.filter_by(group_id=grp.id).first()
        if not pool or float(pool.net_available or 0) <= 0:
            continue

        net = float(pool.net_available or 0)

        # policy
        reserve_pct = float(grp.profit_reserve_pct or 0)
        admin_pct = float(grp.admin_cut_pct or 0)

        reserve_amt = round(net * (reserve_pct / 100.0), 2)
        admin_amt = round(net * (admin_pct / 100.0), 2)
        distributable = round(net - reserve_amt - admin_amt, 2)
        if distributable <= 0:
            continue

        # snapshot deposits
        members_bal = MemberBalance.query.filter_by(group_id=grp.id).all()
        total_deposit = sum(float(m.total_deposit or 0) for m in members_bal)
        if total_deposit <= 0:
            continue

        # create distribution record
        pd = ProfitDistribution(
            group_id=grp.id,
            distributed_at=now,
            total_distributed=distributable,
            reserve_amount=reserve_amt,
            admin_amount=admin_amt,
            note=f"AUTO distribution at {now.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        db.session.add(pd)
        db.session.flush()

        distributed_total_calc = 0.0
        per_user = []
        for mb in members_bal:
            user_deposit = float(mb.total_deposit or 0)
            if user_deposit <= 0:
                share = 0.0
            else:
                share = round((user_deposit / total_deposit) * distributable, 2)
            per_user.append((mb, share))
            distributed_total_calc += share

        # rounding fix
        rounding_diff = round(distributable - distributed_total_calc, 2)
        if rounding_diff != 0:
            for mb, share in reversed(per_user):
                if float(mb.total_deposit or 0) > 0:
                    idx = next(i for i, pair in enumerate(per_user) if pair[0].id == mb.id)
                    per_user[idx] = (mb, round(per_user[idx][1] + rounding_diff, 2))
                    distributed_total_calc = round(distributed_total_calc + rounding_diff, 2)
                    break

        # persist shares
        for mb, share in per_user:
            if share <= 0:
                continue
            psd = ProfitShareDetail(
                distribution_id=pd.id,
                user_id=mb.user_id,
                amount=share,
                deposit_snapshot=mb.total_deposit
            )
            db.session.add(psd)

            mb.interest_earned = (float(mb.interest_earned or 0) + share)
            if hasattr(mb, "last_profit_share_at"):
                mb.last_profit_share_at = now
            db.session.add(mb)

            db.session.add(TransactionLedger(
                group_id=grp.id,
                user_id=mb.user_id,
                ref_type="profit_share",
                ref_id=pd.id,
                amount=share,
                note=f"AUTO profit share {share} from distribution {pd.id}"
            ))

        # admin + reserve ledger
        db.session.add(TransactionLedger(
            group_id=grp.id, user_id=None,
            ref_type="profit_reserve", ref_id=pd.id,
            amount=reserve_amt, note=f"AUTO profit reserve {reserve_amt}"
        ))
        db.session.add(TransactionLedger(
            group_id=grp.id, user_id=None,
            ref_type="admin_cut", ref_id=pd.id,
            amount=admin_amt, note=f"AUTO admin cut {admin_amt}"
        ))

        # update pool
        pool.net_available = round(net - (reserve_amt + admin_amt + distributed_total_calc), 2)
        pool.accrued_interest = max(0, float(pool.accrued_interest or 0) - (distributable + reserve_amt + admin_amt))
        pool.last_updated = now
        db.session.add(pool)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print("⚠️ commit failed for group", grp.id, e)
            continue


# ----- WEBHOOK/CRON: credit_ledger_interest_accrual_job -----
@coop_bp.route("/internal/cron/credit-interest", methods=["POST"])
def credit_ledger_interest_accrual_job():
    """
    SYSTEM JOB (cron/webhook) — accrue interest on CreditLedger balances.
    - Iterates over all credit ledger rows.
    - If last_interest_calc is old, compute accrued interest since then.
    - Updates interest_earned + last_interest_calc.
    - Creates TransactionLedger entry.
    No user/admin notifications triggered (system silent job).
    """
    from cooperative.models import CreditLedger, TransactionLedger

    # optional: auth check via secret header
    secret = request.headers.get("X-CRON-SECRET")
    if secret != os.getenv("CRON_SECRET_KEY", "supersecret"):
        return jsonify({"error": "Unauthorized"}), 403

    now = datetime.utcnow()
    rows = CreditLedger.query.all()
    updated = 0

    for cl in rows:
        if not cl.amount or float(cl.amount) <= 0:
            continue

        last_calc = cl.last_interest_calc or cl.created_at
        days = (now - last_calc).days
        if days <= 0:
            continue

        # simple daily interest accrual (annualized ~10% default)
        rate = 0.10  # 10% yearly, can make configurable
        daily_rate = rate / 365.0
        interest = float(cl.amount) * daily_rate * days
        if interest <= 0:
            continue

        cl.interest_earned = float(cl.interest_earned or 0) + interest
        cl.last_interest_calc = now
        db.session.add(cl)

        db.session.add(TransactionLedger(
            group_id=cl.group_id,
            user_id=cl.user_id,
            ref_type="credit_interest",
            ref_id=cl.id,
            amount=interest,
            note=f"Auto interest accrual for credit balance {cl.amount} over {days} days"
        ))

        updated += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "DB commit failed", "detail": str(e)}), 500

    return jsonify({"message": f"Accrual done", "updated": updated}), 200


# ----- GROUP CREATION: set profit_reserve_pct/admin_cut_pct/distribute_on_profit -----
@coop_bp.route("", methods=["POST"])
@jwt_required()
def create_group():
    """
    Body: { "name": "Seva Samiti", "profit_reserve_pct": 10, "admin_cut_pct": 0, "distribute_on_profit": true }
    Requires: user KYC=verified
    Creates: CooperativeGroup + Hedera vault account (+ associate+KYC for BHC best-effort)
    """
    uid = get_jwt_identity()
    user = User.query.get(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.kyc_status != "verified":
        return jsonify({"error": "KYC required"}), 403

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if len(name) < 3:
        return jsonify({"error": "Name too short (min 3 chars)"}), 400

    # 1) Create Hedera account for the group (vault)
    acct = create_hedera_account(user_id=None, metadata={"type": "cooperative"})
    if not acct or not acct.get("account_id"):
        return jsonify({"error": "Failed to create group Hedera account"}), 500
    coop_acct = acct["account_id"]

    # 2) Profit policy inputs (with safe defaults)
    profit_reserve_pct = float(data.get("profit_reserve_pct", 10.0))  # default 10%
    admin_cut_pct = float(data.get("admin_cut_pct", 0.0))  # default 0%
    distribute_on_profit = bool(data.get("distribute_on_profit", True))
    # 2b) Interest rate (store normalized, e.g. 0.12 = 12%)
    raw_rate = float(data.get("interest_rate", 10.0))  # user may pass 10 or 0.10
    interest_rate = raw_rate / 100.0 if raw_rate > 1 else raw_rate

    # 3) Persist group + creator membership
    slug = _make_slug(name)
    grp = CooperativeGroup(
        name=name,
        slug=slug,
        created_by=user.id,
        cooperative_account_id=coop_acct,
        hedera_private_key=acct["private_key"],
        profit_reserve_pct=profit_reserve_pct,
        admin_cut_pct=admin_cut_pct,
        distribute_on_profit=distribute_on_profit,
        interest_rate=interest_rate  # ✅ added
    )
    db.session.add(grp)
    db.session.flush()  # to get grp.id

    db.session.add(GroupMembership(group_id=grp.id, user_id=user.id, role="admin"))

    # 4) Make token ready (associate + KYC) best-effort
    try:
        token_id = os.getenv("BHC_TOKEN_ID")
        op_key = os.getenv("HEDERA_OPERATOR_KEY")
        if token_id and op_key and coop_acct and acct.get("private_key"):
            ensure_token_ready_for_account(
                token_id=token_id,
                account_id=coop_acct,
                account_private_key=acct["private_key"],
                kyc_grant_signing_key=op_key,
            )
    except Exception as e:
        print("⚠️ Group token-ready setup failed:", e)

    db.session.commit()

    # 🔔 Notification (to creator + verified users)
    push_notification(user.id, f"🎉 Group created: {grp.name} (slug: {grp.slug})", "success")
    verified_user_ids = [u.id for u in User.query.filter(
        User.kyc_status == "verified", User.id != user.id
    ).all()]
    if verified_user_ids:
        push_to_many(verified_user_ids, f"📢 New co-op group created: {grp.name} — use: join group {grp.slug}")

    return jsonify({
        "message": "Group created",
        "group": {
            "name": grp.name,
            "slug": grp.slug,
            "created_by": user.id,
            "cooperative_account_id": grp.cooperative_account_id,
            "members": 1,
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "profit_reserve_pct": profit_reserve_pct,
            "admin_cut_pct": admin_cut_pct,
            "distribute_on_profit": distribute_on_profit,
            "interest_rate": round(interest_rate * 100, 2)
        }
    }), 201


# ----- AUDIT: immutable distribution logging endpoints -----

# GET all profit distributions for a group
@coop_bp.route("/admin/group/<int:group_id>/profit/distributions", methods=["GET"])
@jwt_required()
def list_profit_distributions(group_id):
    uid = get_jwt_identity()
    # admin check
    if not GroupMembership.query.filter_by(group_id=group_id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can view distributions"}), 403

    from cooperative.models import ProfitDistribution
    dists = ProfitDistribution.query.filter_by(group_id=group_id).order_by(
        ProfitDistribution.distributed_at.desc()).all()
    out = []
    for d in dists:
        out.append({
            "id": d.id,
            "distributed_at": d.distributed_at.strftime("%Y-%m-%d %H:%M:%S"),
            "total_distributed": float(d.total_distributed or 0),
            "reserve_amount": float(d.reserve_amount or 0),
            "admin_amount": float(d.admin_amount or 0),
            "note": d.note
        })
    return jsonify(out), 200


# GET profit share details for a distribution
@coop_bp.route("/admin/distribution/<int:dist_id>/shares", methods=["GET"])
@jwt_required()
def list_distribution_shares(dist_id):
    uid = get_jwt_identity()
    from cooperative.models import ProfitDistribution, ProfitShareDetail

    dist = ProfitDistribution.query.get(dist_id)
    if not dist:
        return jsonify({"error": "Distribution not found"}), 404

    # admin check
    if not GroupMembership.query.filter_by(group_id=dist.group_id, user_id=uid, role="admin").first():
        return jsonify({"error": "Only group admin can view shares"}), 403

    shares = ProfitShareDetail.query.filter_by(distribution_id=dist.id).all()
    out = []
    for s in shares:
        out.append({
            "user_id": s.user_id,
            "amount": float(s.amount or 0),
            "deposit_snapshot": float(s.deposit_snapshot or 0)
        })
    return jsonify(out), 200


# -------- GET WITHDRAWALS (history) --------
@coop_bp.route("/<slug>/withdrawals", methods=["GET"])
@jwt_required()
def get_withdrawals(slug):
    uid = get_jwt_identity()
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403

    # 🔹 Withdrawals = ledger entries with ref_type="withdraw"
    q = TransactionLedger.query.filter_by(group_id=grp.id, ref_type="withdraw")

    if membership.role != "admin":
        q = q.filter_by(user_id=uid)

    rows = q.order_by(TransactionLedger.created_at.desc()).all()
    out = []
    for t in rows:
        # note: total_paid = principal + interest (already recorded in ledger.amount)
        out.append({
            "user_id": t.user_id,
            "amount": float(t.amount),
            "interest": None,  # placeholder, unless you tracked separately
            "total_paid": float(t.amount),
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    return jsonify(out), 200


from flask import render_template


@coop_bp.route("/<slug>/member/<int:user_id>/trust", methods=["GET"])
@jwt_required()
def trust_dashboard(slug, user_id):
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return "Group not found", 404

    member = GroupMembership.query.filter_by(group_id=grp.id, user_id=user_id).first()
    if not member:
        return "Member not found", 404

    return render_template(
        "trust_dashboard.html",
        user_id=user_id,
        group_name=grp.name,
        group_slug=grp.slug
    )


# -------- GET TRUSTSCORE --------
@coop_bp.route("/<slug>/trustscore/weekly/<int:user_id>", methods=["GET"])
@jwt_required()
def trustscore_weekly(slug, user_id):
    """
    Return weekly trust score for a member in the group.
    Query param: ?days=7  (optional)
    """
    uid = get_jwt_identity()

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    # Ensure requester is a member (or allow admins to view)
    membership = GroupMembership.query.filter_by(group_id=grp.id, user_id=uid).first()
    if not membership:
        return jsonify({"error": "Not a group member"}), 403


    try:
        days = int(request.args.get("days", 7))
    except Exception:
        days = 7
    # 🔹 Fetch user info for display
    from users.models import User
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404    

    result = calculate_trust_score(user_id=user_id, group_id=grp.id, window_days=days)
    
    # include metadata
    result_meta = {
        "group_id": grp.id,
        "group_slug": grp.slug,
        "group_name": grp.name,
        "user_id": user_id,
        "window_days": days,
        "user_name": user.username, 
        "calculated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }
    return jsonify({"meta": result_meta, "trust": result}), 200


# -------- hedera activity --------
@coop_bp.route("/<slug>/hedera_activity/<int:user_id>", methods=["GET"])
def hedera_activity(slug, user_id):
    """
    Return Hedera activity (wallet linked, KYC file, trust updates, HTS txns) for a user in group
    """
    from cooperative.models import (
        CooperativeGroup, GroupAccountLink, HCSMessageLog,
        ContractEventLog, TrustScoreHistory
    )

    # --- get group_id from slug
    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    group_id = grp.id

    # --- check wallet linked
    wallet_linked = bool(
        grp.cooperative_account_id or
        GroupAccountLink.query.filter_by(group_id=group_id).first()
    )

    # --- check if any KYC file event in HCS logs
    kyc_event = HCSMessageLog.query.filter_by(
        group_id=group_id, msg_type="KYC_FILE"
    ).order_by(HCSMessageLog.created_at.desc()).first()
    kyc_stored = bool(kyc_event)

    # --- check trust score updates from TrustScoreHistory
    trust_event = TrustScoreHistory.query.filter_by(
        user_id=user_id, group_id=group_id
    ).order_by(TrustScoreHistory.created_at.desc()).first()
    trust_updates = bool(trust_event)

    # --- check HTS token txns in contract events
    hts_event = ContractEventLog.query.filter_by(
        group_id=group_id, event_name="HTS_TRANSFER"
    ).order_by(ContractEventLog.created_at.desc()).first()
    hts_txns = bool(hts_event)

    return jsonify({
        "wallet_linked": wallet_linked,
        "kyc_stored": kyc_stored,
        "trust_updates": trust_updates,
        "hts_txns": hts_txns,
    })


# -------- graph 1--------
@coop_bp.route("/<slug>/trustscore/trend/<int:user_id>", methods=["GET"])
@jwt_required()
def trustscore_trend(slug, user_id):
    from cooperative.models import CooperativeGroup, TrustScoreHistory
    from datetime import datetime, timedelta

    grp = CooperativeGroup.query.filter_by(slug=slug).first()
    if not grp:
        return jsonify({"error": "Group not found"}), 404

    # ?days=N (default 30). days<=0 => all history
    try:
        days = int(request.args.get("days", 30))
    except Exception:
        days = 30

    q = (TrustScoreHistory.query
         .filter(TrustScoreHistory.user_id == user_id,
                 TrustScoreHistory.group_id == grp.id))

    if days > 0:
        since = datetime.utcnow() - timedelta(days=days)
        q = q.filter(TrustScoreHistory.created_at >= since)

    history = q.order_by(TrustScoreHistory.created_at.asc()).all()

    data = [{
        "date": h.created_at.strftime("%Y-%m-%d"),
        "score": float(h.score_after)
    } for h in history]

    return jsonify(data), 200

