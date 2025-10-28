# finance/models.py
from datetime import datetime, timedelta
from extensions import db
import json

# --------------------
# Wallet Model
# --------------------
class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # ✅ Add this
    balance = db.Column(db.Float, default=0.0)

# --------------------
# Loan Model
# --------------------
class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='pending')
    next_due_date = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=30))  # पहली EMI 30 दिन बाद

# --------------------
# Voting Model
# --------------------
class Voting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    proposal = db.Column(db.String(255), nullable=False)
    votes_for = db.Column(db.Integer, default=0)
    votes_against = db.Column(db.Integer, default=0)

# --------------------
# Transaction History Model
# --------------------

class TransactionHistory(db.Model):
    __tablename__ = 'transaction_history'

    id = db.Column(db.Integer, primary_key=True)

    # keep legacy column names for backward compatibility
    sender_id = db.Column('user_id', db.Integer, db.ForeignKey('users.id'), nullable=False)   # sender
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)           # receiver

    tx_type = db.Column('type', db.String(50), nullable=False)  # e.g., 'transfer', 'salary', 'loan'
    asset_type = db.Column(db.String(10), nullable=False, default='HBAR')  # 'HBAR' or 'BHC'
    token_id = db.Column(db.String(64))  # e.g., '0.0.6608829' for BHC; NULL for HBAR

    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255))

    # Hedera addressing
    from_account = db.Column(db.String(50))  # '0.0.x' of sender
    to_account = db.Column(db.String(50))    # '0.0.y' of recipient

    # Hedera network details
    hedera_tx_id = db.Column(db.String(255))   # transaction id/hash
    hedera_path = db.Column(db.Text)           # JSON string: ["0.0.sender","0.0.receiver"]

    # Extra context (JSON string)
    meta = db.Column(db.Text)

    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        # best-effort JSON decoding
        try:
            path = json.loads(self.hedera_path) if self.hedera_path else []
        except Exception:
            path = self.hedera_path.split(",") if self.hedera_path else []

        try:
            meta = json.loads(self.meta) if self.meta else {}
        except Exception:
            meta = {"raw": self.meta} if self.meta else {}

        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "type": self.tx_type,
            "asset_type": self.asset_type,
            "token_id": self.token_id,
            "amount": self.amount,
            "description": self.description,
            "from_account": self.from_account,
            "to_account": self.to_account,
            "hedera_tx_id": self.hedera_tx_id,
            "hedera_path": path,
            "meta": meta,
            "timestamp": self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }

# --------------------
# Reward Model
# --------------------
class Reward(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    points = db.Column(db.Integer, default=0)
    reason = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "points": self.points,
            "reason": self.reason,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }

# --------------------
# Fraud Model
# --------------------y

class FraudLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    alerts = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "alerts": self.alerts,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }
    

# --------------------
# DBT Transfer Model
# --------------------
class DBTTransfer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)     # NGO or Admin
    receiver_id = db.Column(db.Integer, nullable=False)   # Beneficiary
    amount = db.Column(db.Float, nullable=False)
    purpose = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "amount": self.amount,
            "purpose": self.purpose,
            "timestamp": self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }

# --------------------
# Deposit Request Model
# --------------------
class DepositRequest(db.Model):
    __tablename__ = "deposit_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(200))  # Reference no, receipt info
    status = db.Column(db.String(20), default="pending")  # pending, approved, rejected
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "amount": self.amount,
            "note": self.note,
            "status": self.status,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        }
# ---------- Outbox / Offline transfer models ----------
from datetime import datetime
from extensions import db  # if your file uses `extensions.db` for SQLAlchemy

class OutboxTransfer(db.Model):
    __tablename__ = "outbox_transfers"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)   # who requested the transfer
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True) # optional user target
    amount = db.Column(db.Float, nullable=False)
    asset_type = db.Column(db.String(16), nullable=False, default="HBAR")         # 'HBAR' | 'BHC'
    token_id = db.Column(db.String(64), nullable=True)                            # HTS token id if BHC
    purpose = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="pending")          # pending, sending, sent, failed
    attempts = db.Column(db.Integer, default=0)                                   # number of send attempts
    last_error = db.Column(db.Text, nullable=True)
    hedera_tx_id = db.Column(db.String(255), nullable=True)                       # last successful tx id
    hedera_path = db.Column(db.Text, nullable=True)                               # optional path/trace JSON
    meta = db.Column(db.Text, nullable=True)                                      # raw payload / context
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "amount": self.amount,
            "asset_type": self.asset_type,
            "token_id": self.token_id,
            "purpose": self.purpose,
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "hedera_tx_id": self.hedera_tx_id,
            "hedera_path": self.hedera_path,
            "meta": self.meta,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class OutboxAttempt(db.Model):
    __tablename__ = "outbox_attempts"

    id = db.Column(db.Integer, primary_key=True)
    outbox_id = db.Column(db.Integer, db.ForeignKey("outbox_transfers.id"), nullable=False)
    attempt_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    success = db.Column(db.Boolean, nullable=False, default=False)
    hedera_tx_id = db.Column(db.String(255), nullable=True)
    response = db.Column(db.Text, nullable=True)    # full response / error text
    error = db.Column(db.Text, nullable=True)

    # relationship for convenience (optional)
    outbox = db.relationship("OutboxTransfer", backref=db.backref("attempts_list", lazy="dynamic"))
