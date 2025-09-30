# safichain/payments/models.py

from datetime import datetime
from extensions import db


class PaymentOrder(db.Model):
    __tablename__ = "payment_orders"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(64), unique=True, nullable=False)   # UUID / timestamp
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Agency / Mint Bank info
    agency_id = db.Column(db.Integer, db.ForeignKey("payment_config.id"), nullable=True, index=True)
    agency_number = db.Column(db.String(32), nullable=True, index=True)  # snapshot of agency mpesa number at order time
    agency = db.relationship("PaymentConfig", backref="orders", lazy=True)

    # Payment info
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(8), default="KES")

    # M-Pesa details
    msisdn = db.Column(db.String(32), nullable=False, index=True)       # user's phone number
    mpesa_ref = db.Column(db.String(64), unique=True, nullable=True)    # M-Pesa transaction ref

    # Status tracking
    status = db.Column(
        db.String(32),
        default="created"
        # values: created / verifying / completed / pending_settlement / failed
    )
    hedera_tx_hash = db.Column(db.String(128), nullable=True)   # Mint Bank → User transfer
    mpesa_raw_payload = db.Column(db.Text, nullable=True)       # full JSON from M-Pesa

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)

    # Relationship
    attempts = db.relationship("PaymentAttempt", backref="order", lazy=True)


class PaymentAttempt(db.Model):
    __tablename__ = "payment_attempts"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.String(64), db.ForeignKey("payment_orders.order_id"), nullable=False
    )

    # Attempt-specific details
    msisdn = db.Column(db.String(32), nullable=False, index=True)
    mpesa_ref = db.Column(db.String(64), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=True)

    # agency snapshot for attempt
    agency_number = db.Column(db.String(32), nullable=True, index=True)

    status = db.Column(
        db.String(32),
        default="verifying"
        # values: verifying / completed / failed / pending_retry
    )

    # Hedera + raw response
    hedera_tx_hash = db.Column(db.String(128), nullable=True)
    mpesa_response = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentConfig(db.Model):
    __tablename__ = "payment_config"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)             # e.g. "Mint Bank" or "Agency A"
    mpesa_number = db.Column(db.String(32), unique=True, nullable=True, index=True)   # e.g. 2547...
    hedera_account_id = db.Column(db.String(64), nullable=True)  # optional: Hedera account (0.0.x)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)              # to mark active configs

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
