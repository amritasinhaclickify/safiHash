import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Union
from cooperative.models import PolicyRule
from extensions import db
from cooperative.models import (
    CooperativeGroup, GroupMembership, Deposit, Repayment, RepaymentSchedule,
    Loan, LoanRequest, VoteDetail, VotingSession, PaymentAudit, PaymentApproval,
    GroupProfitPool, MemberBalance
)

logger = logging.getLogger(__name__)


def _safe_pct(numerator: float, denominator: float) -> float:
    """Return percentage (0..100) safely; handle zero denominator."""
    try:
        if denominator <= 0:
            return 0.0
        return float(numerator) / float(denominator) * 100.0
    except Exception as e:
        logger.exception("Error in _safe_pct: %s", e)
        return 0.0


def _has_attr(model, attr_name: str) -> bool:
    """Safer hasattr check for SQLAlchemy model class attributes."""
    return hasattr(model, attr_name) and getattr(model, attr_name) is not None


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return lo


def _put(params: Dict[str, Any], key: str, val: Optional[Union[float, int]]):
    """Store metric as None (if no-data) or rounded float."""
    params[key] = None if val is None else round(float(val), 2)


def calculate_trust_score(user_id: int, group_id: int, window_days: Optional[int] = None) -> Dict[str, Any]:
    """
    Calculate a 10-parameter trust profile for a user inside a group.
    If window_days is provided, restrict time-based queries to the last `window_days`.
    Returns {"params": {...}, "overall": <0..100>}
    """
    params: Dict[str, Any] = {}
    try:
        cutoff = None
        if window_days:
            try:
                cutoff = datetime.utcnow() - timedelta(days=int(window_days))
            except Exception:
                cutoff = None

        # 1) Deposit Consistency (expected vs actual, with bonus for extra)
        from sqlalchemy import func

        # cutoff handle
        gq = db.session.query(Deposit).filter_by(group_id=group_id)
        uq = db.session.query(Deposit).filter_by(group_id=group_id, user_id=user_id)
        if cutoff and _has_attr(Deposit, "created_at"):
            gq = gq.filter(getattr(Deposit, "created_at") >= cutoff)
            uq = uq.filter(getattr(Deposit, "created_at") >= cutoff)

        # Expected deposits = months in window (at least 1 month)
        if cutoff:
            months_in_window = max(1, (datetime.utcnow().year - cutoff.year) * 12 + (datetime.utcnow().month - cutoff.month) + 1)
        else:
            months_in_window = 1

        expected_deposits = months_in_window  # assume 1 per month required

        # Actual deposits & total amount
        user_deposit_count = uq.count()
        user_deposit_sum = float(uq.with_entities(func.coalesce(func.sum(Deposit.amount), 0)).scalar() or 0.0)

        # Base score = on-time deposits / expected deposits × 100
        base_score = _safe_pct(min(user_deposit_count, expected_deposits), expected_deposits)

        # Bonus for extra deposits or extra amount
        extra_deposits = max(0, user_deposit_count - expected_deposits)
        extra_amount_bonus = 0.0
        if expected_deposits > 0:
            avg_required_amount = (user_deposit_sum / expected_deposits) if user_deposit_count > 0 else 0
            # if paying ≥2x expected amount overall, small bonus
            if avg_required_amount >= 2 * (user_deposit_sum / max(1, user_deposit_count)):
                extra_amount_bonus = 10.0

        bonus = min(20.0, extra_deposits * 5.0 + extra_amount_bonus)

        params["Deposit Consistency"] = round(_clamp(base_score + bonus), 2)

        # 2) Repayment Timeliness (installment-level, due_date vs paid_at)
        grace_days = 3  # optional grace window, adjust as per group rules
        total_installments = 0
        ontime_installments = 0

        rs_q = db.session.query(RepaymentSchedule).join(Loan, RepaymentSchedule.loan_id == Loan.id).filter(
            Loan.group_id == group_id,
            Loan.user_id == user_id
        )

        # Window filter: either due_date ya paid_at cutoff ke baad ho
        if cutoff and _has_attr(RepaymentSchedule, "due_date") and _has_attr(RepaymentSchedule, "paid_at"):
            rs_q = rs_q.filter(
                (getattr(RepaymentSchedule, "due_date") >= cutoff) |
                (getattr(RepaymentSchedule, "paid_at") >= cutoff)
            )

        # Sirf paid installments count karo
        rs_paid = rs_q.filter(RepaymentSchedule.status == "paid").all()
        total_installments = len(rs_paid)

        for inst in rs_paid:
            due = getattr(inst, "due_date", None)
            paid = getattr(inst, "paid_at", None)
            if due and paid:
                if paid <= (due + timedelta(days=grace_days)):
                    ontime_installments += 1

        rt = _safe_pct(ontime_installments, total_installments) if total_installments > 0 else None
        _put(params, "Repayment Timeliness", rt)

        # 3) On-time Repayments Ratio (repayment rows; use paid_repayment_id link; clamp)
        rep_q = db.session.query(Repayment).join(Loan, Repayment.loan_id == Loan.id).filter(
            Loan.group_id == group_id,
            Repayment.payer_id == user_id
        )
        if cutoff and _has_attr(Repayment, "created_at"):
            rep_q = rep_q.filter(getattr(Repayment, "created_at") >= cutoff)
        total_repayments = rep_q.distinct(Repayment.id).count()

        ontime_repayments = 0
        if total_repayments > 0:
            if _has_attr(RepaymentSchedule, "paid_repayment_id") and \
               _has_attr(RepaymentSchedule, "paid_at") and _has_attr(RepaymentSchedule, "due_date"):
                r_q = db.session.query(Repayment.id).join(
                    RepaymentSchedule, Repayment.id == getattr(RepaymentSchedule, "paid_repayment_id")
                ).join(Loan, Repayment.loan_id == Loan.id).filter(
                    Repayment.payer_id == user_id,
                    getattr(RepaymentSchedule, "paid_at") <= getattr(RepaymentSchedule, "due_date"),
                    Loan.group_id == group_id
                )
                if cutoff and _has_attr(Repayment, "created_at"):
                    r_q = r_q.filter(getattr(Repayment, "created_at") >= cutoff)
                ontime_repayments = r_q.distinct(Repayment.id).count()
        oratio = _clamp(_safe_pct(ontime_repayments, total_repayments)) if total_repayments > 0 else None
        _put(params, "On-time Repayments Ratio", oratio)

        # 4) Voting Participation (sessions since user joined; vote rows auto-scoped by session)
        # Get user's group join date
        membership = db.session.query(GroupMembership).filter_by(
            group_id=group_id, user_id=user_id
        ).first()
        join_date = getattr(membership, "joined_at", None)

        sessions_q = db.session.query(VotingSession).filter_by(group_id=group_id)

        # Apply cutoff (window filter)
        if cutoff and _has_attr(VotingSession, "created_at"):
            sessions_q = sessions_q.filter(getattr(VotingSession, "created_at") >= cutoff)

        # Apply join_date filter so only sessions after user joined are counted
        if join_date and _has_attr(VotingSession, "created_at"):
            sessions_q = sessions_q.filter(getattr(VotingSession, "created_at") >= join_date)

        total_sessions = sessions_q.count()

        votes_q = db.session.query(VoteDetail).join(
            VotingSession, VoteDetail.session_id == VotingSession.id
        ).filter(
            VoteDetail.voter_id == user_id,
            VotingSession.group_id == group_id
        )

        vp = _safe_pct(votes_q.count(), total_sessions) if total_sessions > 0 else None
        _put(params, "Voting Participation", vp)

        # 5) Loan Request Frequency (compare to group average, with minimum floor)
        from sqlalchemy import or_

        total_members = db.session.query(GroupMembership).filter_by(group_id=group_id).count() or 1
        lr_user_q = db.session.query(LoanRequest).filter_by(group_id=group_id, user_id=user_id)
        lr_total_q = db.session.query(LoanRequest).filter_by(group_id=group_id)

        if cutoff and _has_attr(LoanRequest, "created_at"):
            lr_user_q = lr_user_q.filter(or_(
                getattr(LoanRequest, "created_at") >= cutoff,
                getattr(LoanRequest, "created_at") == None  # noqa
            ))
            lr_total_q = lr_total_q.filter(or_(
                getattr(LoanRequest, "created_at") >= cutoff,
                getattr(LoanRequest, "created_at") == None  # noqa
            ))

        user_loan_requests = lr_user_q.count()
        total_requests = lr_total_q.count()
        avg_requests_per_member = (total_requests / total_members) if total_members else 0.0

        if avg_requests_per_member <= 0:
            loan_freq_score = 100.0  # koi request hi nahi hui group me
        else:
            ratio = user_loan_requests / avg_requests_per_member
            if ratio <= 1.0:
                loan_freq_score = 100.0
            elif ratio >= 5.0:
                loan_freq_score = 20.0  # floor cap, kabhi 0 nahi hoga
            else:
                # 1x → 100, 5x → 20, linear scale beech me
                loan_freq_score = 100.0 - ((ratio - 1.0) * (80.0 / 4.0))

        _put(params, "Loan Request Frequency", loan_freq_score)

        # 6) Loan Approval / Rejection (derived)
        APPROVED_STATES = {"approved", "disbursed", "active", "closed"}

        user_lr_total_q = db.session.query(LoanRequest).filter_by(group_id=group_id, user_id=user_id)
        user_lr_approved_q = db.session.query(LoanRequest).filter(
            LoanRequest.group_id == group_id,
            LoanRequest.user_id == user_id,
            LoanRequest.status.in_(APPROVED_STATES)
        )

        if cutoff and _has_attr(LoanRequest, "created_at"):
            from sqlalchemy import or_
            user_lr_total_q = user_lr_total_q.filter(or_(
                getattr(LoanRequest, "created_at") >= cutoff,
                getattr(LoanRequest, "created_at") == None  # noqa
            ))
            user_lr_approved_q = user_lr_approved_q.filter(or_(
                getattr(LoanRequest, "created_at") >= cutoff,
                getattr(LoanRequest, "created_at") == None  # noqa
            ))

        user_lr_total = user_lr_total_q.count()
        user_lr_approved = user_lr_approved_q.count()

        approve_pct = _safe_pct(user_lr_approved, user_lr_total) if user_lr_total > 0 else 0.0
        reject_pct = 100.0 - approve_pct if user_lr_total > 0 else 0.0

        # keep only this for 10 cards layout:
        _put(params, "Loan Approval Rate", approve_pct)

        # optional (ONLY if you decide to show it in UI later):
        # _put(params, "Loan Rejection Rate", reject_pct)

        # 7) Disbursal Timeliness (avg days: approved/created -> disbursed)
        approved_loans_q = db.session.query(Loan).filter_by(group_id=group_id, user_id=user_id)
        if cutoff:
            conds = []
            if _has_attr(Loan, "disbursed_at"):
                conds.append(getattr(Loan, "disbursed_at") >= cutoff)
            if _has_attr(Loan, "approved_at"):
                conds.append(getattr(Loan, "approved_at") >= cutoff)
            if _has_attr(Loan, "created_at"):
                conds.append(getattr(Loan, "created_at") >= cutoff)
            if conds:
                from sqlalchemy import or_ as _or
                approved_loans_q = approved_loans_q.filter(_or(*conds))
        approved_loans = approved_loans_q.all()
        total_d = 0.0
        count_d = 0
        for ln in approved_loans:
            disbursed_at = getattr(ln, "disbursed_at", None)
            base_time = getattr(ln, "approved_at", None) or getattr(ln, "created_at", None)
            if disbursed_at and base_time:
                total_d += (disbursed_at - base_time).total_seconds() / (3600 * 24)
                count_d += 1
        if count_d == 0:
            disbursal_score = None
        else:
            avg_days = total_d / count_d
            if avg_days <= 1:   disbursal_score = 100.0
            elif avg_days <= 7: disbursal_score = 75.0
            elif avg_days <= 14: disbursal_score = 50.0
            elif avg_days <= 30: disbursal_score = 25.0
            else:                disbursal_score = 0.0
        _put(params, "Disbursal Timeliness", disbursal_score)

        # 8) Self-Repayment Rate (among repayments that target user's loans)
        tr_q = db.session.query(Repayment).join(Loan, Repayment.loan_id == Loan.id).filter(
            Loan.group_id == group_id, Loan.user_id == user_id
        )
        if cutoff and _has_attr(Repayment, "created_at"):
            tr_q = tr_q.filter(getattr(Repayment, "created_at") >= cutoff)
        total_repayments_for_user_loans = tr_q.count()
        if total_repayments_for_user_loans == 0:
            srr = None
        else:
            self_paid = tr_q.filter(Repayment.payer_id == user_id).count()
            srr = _safe_pct(self_paid, total_repayments_for_user_loans)
        _put(params, "Self-Repayment Rate", srr)

        # 9) Third-Party Payment Flag (higher = less suspicious)
        pa_q = db.session.query(PaymentAudit).filter(
            PaymentAudit.group_id == group_id,
            PaymentAudit.borrower_id == user_id,
            PaymentAudit.status == "SUSPECT"
        )
        if cutoff and _has_attr(PaymentAudit, "created_at"):
            pa_q = pa_q.filter(getattr(PaymentAudit, "created_at") >= cutoff)
        suspect_count = pa_q.count()
        if total_repayments_for_user_loans == 0:
            tppf = None
        else:
            suspect_percent = _safe_pct(suspect_count, total_repayments_for_user_loans)
            tppf = max(0.0, 100.0 - suspect_percent)
        _put(params, "Third-Party Payment Flag", tppf)

        # 10) Profit Contribution Share (sum amounts in window)
        total_deposit_sum_q = db.session.query(db.func.coalesce(db.func.sum(Deposit.amount), 0)).filter_by(group_id=group_id)
        user_deposit_sum_q = db.session.query(db.func.coalesce(db.func.sum(Deposit.amount), 0)).filter_by(group_id=group_id, user_id=user_id)
        if cutoff and _has_attr(Deposit, "created_at"):
            total_deposit_sum_q = total_deposit_sum_q.filter(getattr(Deposit, "created_at") >= cutoff)
            user_deposit_sum_q = user_deposit_sum_q.filter(getattr(Deposit, "created_at") >= cutoff)
        total_deposit_sum = float(total_deposit_sum_q.scalar() or 0.0)
        user_deposit_sum = float(user_deposit_sum_q.scalar() or 0.0)
        pcs = _safe_pct(user_deposit_sum, total_deposit_sum) if total_deposit_sum > 0 else None
        _put(params, "Profit Contribution Share", pcs)

    except Exception as e:
        logger.exception("Error calculating trust score for user %s in group %s: %s", user_id, group_id, e)
        for k in [
            "Deposit Consistency","Repayment Timeliness","On-time Repayments Ratio",
            "Voting Participation","Loan Request Frequency","Loan Approval Rate",
            "Disbursal Timeliness","Self-Repayment Rate","Third-Party Payment Flag",
            "Profit Contribution Share"
        ]:
            params.setdefault(k, None)

    # Overall = weighted average using PolicyRule weights (None excluded)
    try:
        rule = db.session.query(PolicyRule).filter_by(group_id=group_id).first()
        if rule:
            weights = {
                "Deposit Consistency": float(rule.w_deposit_consistency or 0),
                "Repayment Timeliness": float(rule.w_repayment_timeliness or 0),
                "On-time Repayments Ratio": float(rule.w_ontime_repayments or 0),
                "Voting Participation": float(rule.w_voting_participation or 0),
                "Loan Request Frequency": float(rule.w_loan_request_freq or 0),
                "Loan Approval Rate": float(rule.w_loan_approval_rate or 0),
                "Disbursal Timeliness": float(rule.w_disbursal_timeliness or 0),
                "Self-Repayment Rate": float(rule.w_self_repayment or 0),
                "Third-Party Payment Flag": float(rule.w_thirdparty_flag or 0),
                "Profit Contribution Share": float(rule.w_profit_contribution or 0),
            }

            weighted_sum = 0.0
            total_weight = 0.0

            for k, v in params.items():
                if isinstance(v, (int, float)):
                    w = weights.get(k, 0.0)
                    weighted_sum += v * w
                    total_weight += w

            overall = _clamp(round(weighted_sum / total_weight, 2)) if total_weight > 0 else 0.0
        else:
            # Fallback: simple average if no PolicyRule exists
            vals = [v for v in params.values() if isinstance(v, (int, float))]
            overall = _clamp(round(sum(vals) / max(1, len(vals)), 2)) if vals else 0.0

    except Exception as e:
        logger.exception("Error computing overall trust score: %s", e)
        overall = 0.0

