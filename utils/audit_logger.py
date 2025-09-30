# utils/audit_logger.py
import json
import uuid
import traceback
from datetime import datetime

from audit.models import AuditLog
from extensions import db
from config import Config

# Use the standardized consensus helper (handles Java-binding + fallbacks)
from utils.consensus_helper import publish_to_consensus as consensus_publish

def publish_to_consensus(message):
    """
    Thin wrapper that uses the project's standardized consensus helper.
    Keeps a uniform shape for callers that expect a dict response.
    """
    try:
        return consensus_publish(message)
    except Exception as e:
        # Ensure we always return a dict, never raise here
        tb = traceback.format_exc()
        print(f"[Audit Logger] consensus_publish failed: {e}\n{tb}")
        return {"status": "error", "error": str(e), "traceback": tb}

def log_audit_action(user_id, action, table_name, record_id=None, old=None, new=None):
    """
    Logs action locally in DB and publishes an immutable record to Hedera via consensus helper.
    This function is resilient: DB errors will not prevent attempting a Hedera publish, and vice-versa.
    """
    # Normalize values for DB storage
    old_json = json.dumps(old, default=str) if old else None
    new_json = json.dumps(new, default=str) if new else None

    # 1) Save to local DB (best-effort)
    log_entry = None
    try:
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            table_name=table_name,
            record_id=record_id,
            old_value=old_json,
            new_value=new_json,
            created_at=datetime.utcnow()
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception as db_err:
        # Rollback to keep session clean and continue
        try:
            db.session.rollback()
        except Exception:
            pass
        print(f"[Audit Logger] Failed to save locally: {db_err}")
        log_entry = None

    # 2) Publish to Hedera Consensus (use helper; do not crash caller)
    try:
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "action": action,
            "table": table_name,
            "record_id": record_id,
            "old": old,
            "new": new,
            "local_log_id": getattr(log_entry, "id", None)
        }
        res = consensus_publish(payload)
        # optional: log publish result to stdout for debugging
        if res.get("status") == "error":
            print(f"[Audit Logger] Hedera publish returned error: {res}")
        return res
    except Exception as hedera_err:
        tb = traceback.format_exc()
        print(f"[Audit Logger] Failed to send to Hedera: {hedera_err}\n{tb}")
        return {"status": "error", "error": str(hedera_err), "traceback": tb}
