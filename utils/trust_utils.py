import logging
from cooperative.models import (
    CooperativeGroup, GroupMembership, Deposit, Repayment, RepaymentSchedule,
    Loan, LoanRequest, VoteDetail, VotingSession, PaymentAudit, PaymentApproval,
    GroupProfitPool, MemberBalance
)
from extensions import db
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

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


def calculate_trust_score(user_id: int, group_id: int, window_days: Optional[int] = None) -> Dict[str, Any]:
    """
    Calculate a 10-parameter trust profile for a user inside a group.
    If window_days is provided, restrict time-based queries to the last `window_days`.
    Returns {"params": {...}, "overall": <0..100>}
    """
    params: Dict[str, float] = {}
    try:
        cutoff = None
        if window_days:
            try:
                cutoff = datetime.utcnow() - timedelta(days=int(window_days))
            except Exception:
                cutoff = None

        # 1) Deposit Consistency (counts within window)
        gq = db.session.query(Deposit).filter_by(group_id=group_id)
        uq = db.session.query(Deposit).filter_by(group_id=group_id, user_id=user_id)
        if cutoff and _has_attr(Deposit, "created_at"):
            gq = gq.filter(getattr(Deposit, "created_at") >= cutoff)
            uq = uq.filter(getattr(Deposit, "created_at") >= cutoff)
        total_group_deposits = gq.count()
        user_deposits = uq.count()
        params["Deposit Consistency"] = round(_safe_pct(user_deposits, total_group_deposits), 2)

        # 2) Repayment Timeliness (installment-based, respects window on due/paid_at)
        user_loans_q = db.session.query(Loan).filter_by(group_id=group_id, user_id=user_id)
        if cutoff and _has_attr(Loan, "disbursed_at"):
            user_loans_q = user_loans_q.filter(
                (getattr(Loan, "disbursed_at") >= cutoff) | (getattr(Loan, "created_at") >= cutoff)
            )
        user_loans = user_loans_q.all()
        loan_ids = [l.id for l in user_loans] if user_loans else []
        total_installments = 0
        ontime_installments = 0
        if loan_ids:
            rs_q = db.session.query(RepaymentSchedule).filter(RepaymentSchedule.loan_id.in_(loan_ids))
            if cutoff and _has_attr(RepaymentSchedule, "paid_at") and _has_attr(RepaymentSchedule, "due_date"):
                # विंडो में आने वाली किस्तें: जिनकी due_date विंडो में है या paid_at विंडो में है
                rs_q = rs_q.filter(
                    (getattr(RepaymentSchedule, "due_date") >= cutoff) |
                    (getattr(RepaymentSchedule, "paid_at") >= cutoff)
                )
            # ✅ सिर्फ paid वाली किस्तों पर timeliness measure करें
            rs_paid = rs_q.filter(RepaymentSchedule.status == "paid")
            total_installments = rs_paid.count()
            if _has_attr(RepaymentSchedule, "paid_at") and _has_attr(RepaymentSchedule, "due_date"):
                ontime_installments = rs_paid.filter(
                    getattr(RepaymentSchedule, "paid_at") <= getattr(RepaymentSchedule, "due_date")
                ).count()
        params["Repayment Timeliness"] = round(_safe_pct(ontime_installments, total_installments), 2)

        # 3) On-time Repayments Ratio (repayment rows linked to schedules)
        from sqlalchemy import or_

        # base: केवल वही repayments गिने जो किसी schedule से लिंक हों
        rq_base = (db.session.query(Repayment.id)
        .join(RepaymentSchedule, Repayment.id == getattr(RepaymentSchedule, "paid_repayment_id"))
        .join(Loan, Repayment.loan_id == Loan.id)
        .filter(
            Loan.group_id == group_id,
            Repayment.payer_id == user_id
        ))

        # window: schedule.paid_at या schedule.due_date पर लगाओ (created_at नहीं)
        if cutoff and _has_attr(RepaymentSchedule, "paid_at") and _has_attr(RepaymentSchedule, "due_date"):
            rq_base = rq_base.filter(
                or_(
                    getattr(RepaymentSchedule, "paid_at") >= cutoff,
                    getattr(RepaymentSchedule, "due_date") >= cutoff
                )
            )

        total_repayments = rq_base.distinct(Repayment.id).count()

        ontime_repayments = 0
        if total_repayments > 0 and _has_attr(RepaymentSchedule, "paid_at") and _has_attr(RepaymentSchedule,
                                                                                          "due_date"):
            rq_ontime = rq_base.filter(
                getattr(RepaymentSchedule, "paid_at") <= getattr(RepaymentSchedule, "due_date")
            )
            ontime_repayments = rq_ontime.distinct(Repayment.id).count()

        params["On-time Repayments Ratio"] = round(_safe_pct(ontime_repayments, total_repayments), 2)

        # 4) Voting Participation (uses VotingSession.created_at)
        sessions_q = db.session.query(VotingSession).filter_by(group_id=group_id)
        if cutoff and _has_attr(VotingSession, "created_at"):
            sessions_q = sessions_q.filter(getattr(VotingSession, "created_at") >= cutoff)
        total_sessions = sessions_q.count()

        votes_q = db.session.query(VoteDetail).join(
            VotingSession, VoteDetail.session_id == VotingSession.id
        ).filter(
            VoteDetail.voter_id == user_id,
            VotingSession.group_id == group_id
        )
        # ⚠️ सिर्फ session window filter करो, VoteDetail.created_at पर ज़रूरी नहीं
        user_votes = votes_q.count()

        params["Voting Participation"] = round(_safe_pct(user_votes, total_sessions), 2)

        # --- 5) Loan Request Frequency (inverse normalized) ---
        from sqlalchemy import or_

        total_members = db.session.query(GroupMembership).filter_by(group_id=group_id).count() or 1

        # base queries
        lr_user_q = db.session.query(LoanRequest).filter_by(group_id=group_id, user_id=user_id)
        lr_total_q = db.session.query(LoanRequest).filter_by(group_id=group_id)

        # time-window with fallbacks if created_at missing
        if cutoff and _has_attr(LoanRequest, "created_at"):
            # include rows where created_at >= cutoff OR (created_at is NULL but linked Loan/VotingSession time >= cutoff)
            lr_user_q = lr_user_q.filter(
                or_(
                    getattr(LoanRequest, "created_at") >= cutoff,
                    getattr(LoanRequest, "created_at") == None  # noqa
                )
            )
            lr_total_q = lr_total_q.filter(
                or_(
                    getattr(LoanRequest, "created_at") >= cutoff,
                    getattr(LoanRequest, "created_at") == None  # noqa
                )
            )

        user_loan_requests = lr_user_q.count()
        total_requests = lr_total_q.count() or 0
        avg_requests_per_member = (total_requests / total_members) if total_members else 0

        if avg_requests_per_member <= 0:
            loan_freq_score = 100.0
        else:
            ratio = user_loan_requests / avg_requests_per_member
            if ratio <= 1:
                loan_freq_score = 100.0
            elif ratio >= 4:
                loan_freq_score = 0.0
            else:
                # 1x → 100, 2x → 50, 3x → 25, 4x+ → 0
                loan_freq_score = 100.0 * (4.0 - ratio) / 3.0

        params["Loan Request Frequency"] = round(loan_freq_score, 2)

        # --- 6) Loan Approval Rate ---
        APPROVED_STATES = {"approved", "disbursed", "active", "closed"}

        user_lr_total_q = db.session.query(LoanRequest).filter_by(group_id=group_id, user_id=user_id)
        user_lr_approved_q = db.session.query(LoanRequest).filter(
            LoanRequest.group_id == group_id,
            LoanRequest.user_id == user_id,
            LoanRequest.status.in_(APPROVED_STATES)
        )

        if cutoff and _has_attr(LoanRequest, "created_at"):
            user_lr_total_q = user_lr_total_q.filter(
                or_(getattr(LoanRequest, "created_at") >= cutoff,
                    getattr(LoanRequest, "created_at") == None)  # noqa
            )
            user_lr_approved_q = user_lr_approved_q.filter(
                or_(getattr(LoanRequest, "created_at") >= cutoff,
                    getattr(LoanRequest, "created_at") == None)  # noqa
            )

        user_lr_total = user_lr_total_q.count()
        user_lr_approved = user_lr_approved_q.count()
        params["Loan Approval Rate"] = round(_safe_pct(user_lr_approved, user_lr_total), 2)

        # 7) Disbursal Timeliness (avg days: approved/created -> disbursed, in window)
        approved_loans_q = db.session.query(Loan).filter_by(group_id=group_id, user_id=user_id)
        if cutoff:
            from sqlalchemy import or_
            conds = []
            if _has_attr(Loan, "disbursed_at"):
                conds.append(getattr(Loan, "disbursed_at") >= cutoff)
            if _has_attr(Loan, "approved_at"):
                conds.append(getattr(Loan, "approved_at") >= cutoff)
            if _has_attr(Loan, "created_at"):
                conds.append(getattr(Loan, "created_at") >= cutoff)
            if conds:
                approved_loans_q = approved_loans_q.filter(or_(*conds))
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
            disbursal_score = 0.0  # ❗अब no-data पर 100 नहीं, 0
        else:
            avg_days = total_d / count_d
            if avg_days <= 1:   disbursal_score = 100.0
            elif avg_days <= 7: disbursal_score = 75.0
            elif avg_days <= 14: disbursal_score = 50.0
            elif avg_days <= 30: disbursal_score = 25.0
            else:                disbursal_score = 0.0
        params["Disbursal Timeliness"] = round(disbursal_score, 2)

        # 8) Self-Repayment Rate (among repayments for user's loans)
        tr_q = db.session.query(Repayment).join(Loan, Repayment.loan_id == Loan.id).filter(
            Loan.group_id == group_id, Loan.user_id == user_id
        )
        if cutoff and _has_attr(Repayment, "created_at"):
            tr_q = tr_q.filter(getattr(Repayment, "created_at") >= cutoff)
        total_repayments_for_user_loans = tr_q.count()
        if total_repayments_for_user_loans == 0:
            params["Self-Repayment Rate"] = 0.0   # ❗no-data -> 0
        else:
            self_paid = tr_q.filter(Repayment.payer_id == user_id).count()
            params["Self-Repayment Rate"] = round(_safe_pct(self_paid, total_repayments_for_user_loans), 2)

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
            third_party_score = 0.0  # ❗कोई repayment नहीं तो 100% मत दो
        else:
            suspect_percent = _safe_pct(suspect_count, total_repayments_for_user_loans)
            third_party_score = max(0.0, 100.0 - suspect_percent)
        params["Third-Party Payment Flag"] = round(third_party_score, 2)

        # 10) Profit Contribution Share (sum amounts in window)
        total_deposit_sum_q = db.session.query(db.func.coalesce(db.func.sum(Deposit.amount), 0)).filter_by(group_id=group_id)
        user_deposit_sum_q = db.session.query(db.func.coalesce(db.func.sum(Deposit.amount), 0)).filter_by(group_id=group_id, user_id=user_id)
        if cutoff and _has_attr(Deposit, "created_at"):
            total_deposit_sum_q = total_deposit_sum_q.filter(getattr(Deposit, "created_at") >= cutoff)
            user_deposit_sum_q = user_deposit_sum_q.filter(getattr(Deposit, "created_at") >= cutoff)
        total_deposit_sum = float(total_deposit_sum_q.scalar() or 0.0)
        user_deposit_sum = float(user_deposit_sum_q.scalar() or 0.0)
        params["Profit Contribution Share"] = round(_safe_pct(user_deposit_sum, total_deposit_sum), 2)

    except Exception as e:
        logger.exception("Error calculating trust score for user %s in group %s: %s", user_id, group_id, e)
        for k in [
            "Deposit Consistency","Repayment Timeliness","On-time Repayments Ratio",
            "Voting Participation","Loan Request Frequency","Loan Approval Rate",
            "Disbursal Timeliness","Self-Repayment Rate","Third-Party Payment Flag",
            "Profit Contribution Share"
        ]:
            params.setdefault(k, 0.0)

    # Overall = simple mean
    try:
        vals = list(params.values()) if params else [0.0]
        overall = _clamp(round(sum(vals) / max(1, len(vals)), 2))
    except Exception as e:
        logger.exception("Error computing overall trust score: %s", e)
        overall = 0.0

    return {"params": params, "overall": overall}
