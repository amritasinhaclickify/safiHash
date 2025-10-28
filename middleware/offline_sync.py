# middleware/offline_sync.py
import time
from datetime import datetime
from extensions import db
from finance.models import OutboxTransfer, TransactionHistory
import json

def process_outbox():
    """
    Retry pending on-chain transfers that failed DB write earlier.
    """
    print("🔄 Outbox retry started...")
    pending = OutboxTransfer.query.filter_by(status="pending").all()

    for row in pending:
        try:
            # Check if already exists (idempotent)
            exists = TransactionHistory.query.filter_by(hedera_tx_id=row.hedera_tx_id).first()
            if exists:
                print(f"⏭️ Already recorded in TransactionHistory: {row.hedera_tx_id}")
                row.status = "done"
                db.session.commit()
                continue

            # Reconstruct minimal record
            txn = TransactionHistory(
                sender_id=row.sender_id,
                recipient_id=row.recipient_id,
                tx_type="transfer",
                asset_type=row.asset_type,
                token_id=row.token_id,
                amount=row.amount,
                description=row.purpose or f"Recovered {row.asset_type} transfer",
                from_account=None,
                to_account=None,
                hedera_tx_id=row.hedera_tx_id,
                hedera_path=row.hedera_path,
                meta=row.meta,
                timestamp=datetime.utcnow(),
            )

            db.session.add(txn)
            row.status = "done"
            row.updated_at = datetime.utcnow()
            db.session.commit()

            print(f"✅ Outbox transfer restored to DB: {row.hedera_tx_id}")

        except Exception as e:
            db.session.rollback()
            row.attempts = (row.attempts or 0) + 1
            row.last_error = str(e)
            row.updated_at = datetime.utcnow()
            db.session.commit()
            print(f"⚠️ Retry failed for tx {row.hedera_tx_id}: {e}")

    print("✅ Outbox retry finished.")
