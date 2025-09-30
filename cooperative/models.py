# cooperative/models.py
from extensions import db
from datetime import datetime
from sqlalchemy import Numeric

class CooperativeGroup(db.Model):
    __tablename__ = "cooperative_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)  # easy join code / group-id
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)  # creator (User.id)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hedera_private_key = db.Column(db.String, nullable=True)
    interest_rate = db.Column(db.Float, default=0.10)   # default 10% yearly
    min_balance = db.Column(db.Float, default=0.0)      # default no condition

    # Optional: link group with Hedera account (for collective wallet)
    cooperative_account_id = db.Column(db.String(100), nullable=True)

    # Profit-sharing policy fields
    profit_reserve_pct = db.Column(db.Float, default=10.0)   # % kept as reserve from profit (e.g. 10%)
    admin_cut_pct = db.Column(db.Float, default=0.0)         # % of profit given to admin/ops
    distribute_on_profit = db.Column(db.Boolean, nullable=False, default=True)  # auto distribute flag
    last_profit_settlement = db.Column(db.DateTime, nullable=True)

    members = db.relationship("GroupMembership", backref="group", cascade="all, delete-orphan")


class GroupMembership(db.Model):
    __tablename__ = "group_memberships"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(50), default="member")  # member | admin
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    # unique constraint: 1 user = 1 membership per group
    __table_args__ = (db.UniqueConstraint("group_id", "user_id", name="uq_group_user"),)



class Deposit(db.Model):
    __tablename__ = "deposits"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MemberBalance(db.Model):
    __tablename__ = "member_balances"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    total_deposit = db.Column(db.Float, nullable=False, default=0.0)     # kitna jama kiya
    interest_earned = db.Column(Numeric(18, 2), nullable=False, default=0)  # profit-share / dividend mila
    total_withdrawn = db.Column(Numeric(18, 2), nullable=False, default=0)  # kitna nikaala

    # track kab last profit share mila
    last_profit_share_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("group_id", "user_id", name="uq_group_user_balance"),)



class LoanRequest(db.Model):
    __tablename__ = "loan_requests"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending | approved | rejected
    purpose = db.Column(db.String(200), nullable=True)    # ✅ new field
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



class Vote(db.Model):
    __tablename__ = "votes"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loan_requests.id"), nullable=False)
    voter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    decision = db.Column(db.String(10), nullable=False)  # yes | no
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Repayment(db.Model):
    __tablename__ = "repayments"

    id = db.Column(db.Integer, primary_key=True)
    # ✅ fix: link repayments to Loan, not LoanRequest
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False, index=True)

    payer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TrustScore(db.Model):
    __tablename__ = "trust_scores"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    score = db.Column(db.Float, default=0.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Alert(db.Model):
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    level = db.Column(db.String(20), default="info")  # info | warning | critical
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---- ADD MODELS (paste anywhere below existing models) ----
class TransactionLedger(db.Model):
    __tablename__ = "transaction_ledger"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    user_id  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    ref_type = db.Column(db.String(40), nullable=False)   # deposit|loan_disbursal|repayment|penalty|fee|adjustment
    ref_id   = db.Column(db.Integer, nullable=True)       # Deposit.id / LoanRequest.id / Repayment.id etc.
    amount   = db.Column(Numeric(18,2), nullable=False)
    note     = db.Column(db.String(255), nullable=True)

    hcs_topic_id = db.Column(db.String(64), nullable=True)
    hcs_seq      = db.Column(db.BigInteger, nullable=True)
    tx_hash      = db.Column(db.String(128), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class VotingSession(db.Model):
    __tablename__ = "voting_sessions"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    loan_request_id = db.Column(db.Integer, db.ForeignKey("loan_requests.id"), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="ongoing")
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at  = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # ← new


class VoteDetail(db.Model):
    __tablename__ = "vote_details"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("voting_sessions.id"), nullable=False, index=True)
    voter_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    choice     = db.Column(db.String(5), nullable=False)  # yes|no
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("session_id", "voter_id", name="uq_session_voter"),)



# ===== LOAN (separate from request) =====
class Loan(db.Model):
    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    loan_request_id = db.Column(db.Integer, db.ForeignKey("loan_requests.id"), nullable=False, unique=True, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    user_id  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    principal = db.Column(Numeric(18,2), nullable=False)
    interest_rate_apy = db.Column(Numeric(5,2), nullable=False, default=0)  # e.g. 12.50
    tenure_months = db.Column(db.Integer, nullable=False, default=12)
    status = db.Column(db.String(20), nullable=False, default="active")  # active|closed|defaulted|cancelled
    disbursed_at = db.Column(db.DateTime, nullable=True)
    closed_at    = db.Column(db.DateTime, nullable=True)
    created_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

# ===== REPAYMENT SCHEDULE =====
class RepaymentSchedule(db.Model):
    __tablename__ = "repayment_schedules"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False, index=True)
    installment_no = db.Column(db.Integer, nullable=False)  # 1..N
    due_date = db.Column(db.DateTime, nullable=False, index=True)
    due_amount = db.Column(Numeric(18,2), nullable=False)
    principal_component = db.Column(Numeric(18,2), nullable=False, default=0)
    interest_component  = db.Column(Numeric(18,2), nullable=False, default=0)
    status = db.Column(db.String(15), nullable=False, default="due")  # due|paid|overdue|waived
    paid_at = db.Column(db.DateTime, nullable=True)
    paid_repayment_id = db.Column(db.Integer, db.ForeignKey("repayments.id"), nullable=True)


    __table_args__ = (db.UniqueConstraint("loan_id", "installment_no", name="uq_loan_installment"),)

# ===== GROUP WALLET / ACCOUNT LINK =====
class GroupAccountLink(db.Model):
    __tablename__ = "group_account_links"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, unique=True, index=True)
    hedera_account_id = db.Column(db.String(64), nullable=False)  # mirrors cooperative_account_id, but centralized here
    hcs_topic_id = db.Column(db.String(64), nullable=True)        # consensus topic for the group
    treasury_token_id = db.Column(db.String(64), nullable=True)   # e.g., BHC token id
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# ===== HCS MESSAGE LOG =====
class HCSMessageLog(db.Model):
    __tablename__ = "hcs_message_logs"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    topic_id = db.Column(db.String(64), nullable=True, index=True)
    sequence_no = db.Column(db.BigInteger, nullable=True, index=True)
    msg_type = db.Column(db.String(40), nullable=False)  # DEPOSIT|LOAN_REQUEST|VOTE|DISBURSAL|REPAYMENT|ALERT|POLICY
    payload = db.Column(db.Text, nullable=True)          # raw JSON/string
    tx_hash = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

# ===== CONTRACT EVENT LOG (HTS/SC events) =====
class ContractEventLog(db.Model):
    __tablename__ = "contract_event_logs"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=True, index=True)
    contract_id = db.Column(db.String(64), nullable=True, index=True)
    event_name = db.Column(db.String(80), nullable=False)
    tx_hash = db.Column(db.String(128), nullable=True, index=True)
    payload = db.Column(db.Text, nullable=True)  # decoded args JSON
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
# ===== POLICY RULES / LIMITS =====
class PolicyRule(db.Model):
    __tablename__ = "policy_rules"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, unique=True, index=True)

    # Loan / governance rules
    quorum_percent = db.Column(Numeric(5,2), nullable=False, default=50)       # e.g., 50 = simple majority
    max_loan_pct_of_pool = db.Column(Numeric(6,2), nullable=False, default=25) # e.g., 25% of current pool
    max_loan_per_member = db.Column(Numeric(18,2), nullable=True)              # absolute cap
    min_deposit_amount = db.Column(Numeric(18,2), nullable=True)
    penalty_rate_monthly = db.Column(Numeric(6,2), nullable=True)              # overdue penalty

    # Trust score weights (sum ideally = 100)
    w_deposit_consistency = db.Column(Numeric(5,2), nullable=False, default=15)
    w_repayment_timeliness = db.Column(Numeric(5,2), nullable=False, default=20)
    w_ontime_repayments = db.Column(Numeric(5,2), nullable=False, default=15)
    w_voting_participation = db.Column(Numeric(5,2), nullable=False, default=5)
    w_loan_request_freq = db.Column(Numeric(5,2), nullable=False, default=5)
    w_loan_approval_rate = db.Column(Numeric(5,2), nullable=False, default=10)
    w_disbursal_timeliness = db.Column(Numeric(5,2), nullable=False, default=10)
    w_self_repayment = db.Column(Numeric(5,2), nullable=False, default=10)
    w_thirdparty_flag = db.Column(Numeric(5,2), nullable=False, default=5)
    w_profit_contribution = db.Column(Numeric(5,2), nullable=False, default=5)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

# ===== TRUST SCORE HISTORY =====
class TrustScoreHistory(db.Model):
    __tablename__ = "trust_score_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=True, index=True)
    delta = db.Column(Numeric(8,2), nullable=False)     # +/-
    score_after = db.Column(Numeric(8,2), nullable=False)
    reason = db.Column(db.String(120), nullable=False)  # e.g., DEPOSIT, ONTIME_EMI, OVERDUE, VOTE_PARTICIPATION
    ref_table = db.Column(db.String(40), nullable=True) # deposits|repayments|loan_requests|loans...
    ref_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    onchain_tx = db.Column(db.String(128), nullable=True, index=True)  # Hedera tx hash (proof)


# ===== UPDATED: CreditLedger (with interest accrual) =====
class CreditLedger(db.Model):
    __tablename__ = "credit_ledger"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    user_id  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    loan_id  = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=True, index=True)  # optional link if credit is tied to a loan
    amount   = db.Column(Numeric(18,2), nullable=False, default=0)   # parked / saved amount
    interest_earned = db.Column(Numeric(18,2), nullable=False, default=0)  # total interest earned on parked credit
    last_interest_calc = db.Column(db.DateTime, nullable=True)       # last time interest was calculated
    source   = db.Column(db.String(40), nullable=True)               # e.g., OVERPAYMENT|REFUND|MANUAL_ADJUST
    note     = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("group_id", "user_id", name="uq_group_user_credit"),)



# ===== NEW: PaymentAudit (suspicious / historic payment records) =====
class PaymentAudit(db.Model):
    __tablename__ = "payment_audits"

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, nullable=True, index=True)   # original Repayment.id if exists
    group_id   = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=True, index=True)
    loan_id    = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=True, index=True)
    payer_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    borrower_id= db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    amount     = db.Column(Numeric(18,2), nullable=False)
    applied_amount = db.Column(Numeric(18,2), nullable=True)  # amount actually applied to loan
    status     = db.Column(db.String(40), nullable=False)     # e.g., SUSPECT|APPROVED|REFUNDED|FLAGGED
    reason     = db.Column(db.String(255), nullable=True)
    raw_metadata = db.Column("metadata", db.Text, nullable=True)   # raw JSON string if needed
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


# ===== NEW: PaymentApproval (third-party payments / agent approvals) =====
class PaymentApproval(db.Model):
    __tablename__ = "payment_approvals"

    id = db.Column(db.Integer, primary_key=True)
    repayment_id = db.Column(db.Integer, db.ForeignKey("repayments.id"), nullable=True, index=True)
    payer_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    approver_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)  # admin who approved
    is_agent_payment = db.Column(db.Boolean, nullable=False, default=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    approved_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# ====== PROFIT / DIVIDEND MODELS ======
class GroupProfitPool(db.Model):
    __tablename__ = "group_profit_pool"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    accrued_interest = db.Column(Numeric(18,2), nullable=False, default=0)  # interest collected from loans
    expenses = db.Column(Numeric(18,2), nullable=False, default=0)          # admin fees / reserves taken
    net_available = db.Column(Numeric(18,2), nullable=False, default=0)     # accrued_interest - expenses
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ProfitDistribution(db.Model):
    __tablename__ = "profit_distributions"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("cooperative_groups.id"), nullable=False, index=True)
    distributed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    total_distributed = db.Column(Numeric(18,2), nullable=False, default=0)
    reserve_amount = db.Column(Numeric(18,2), nullable=False, default=0)
    admin_amount = db.Column(Numeric(18,2), nullable=False, default=0)
    note = db.Column(db.String(255), nullable=True)

class ProfitShareDetail(db.Model):
    __tablename__ = "profit_share_details"

    id = db.Column(db.Integer, primary_key=True)
    distribution_id = db.Column(db.Integer, db.ForeignKey("profit_distributions.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    amount = db.Column(Numeric(18,2), nullable=False, default=0)
    deposit_snapshot = db.Column(db.Float, nullable=False, default=0.0) # user's deposit at snapshot time
