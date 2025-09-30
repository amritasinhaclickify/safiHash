# utils/alert_trigger.py
import json
import traceback
from datetime import datetime

from extensions import db
from security.models import AlertLog

# Use the standardized consensus helper
from utils.consensus_helper import publish_to_consensus as consensus_publish

def publish_to_consensus(message):
    """
    Thin wrapper to keep backward compatibility with older callers.
    Always returns a dict.
    """
    try:
        return consensus_publish(message)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[Alert Trigger] consensus_publish failed: {e}\n{tb}")
        return {"status": "error", "error": str(e), "traceback": tb}

def trigger_alert(user_id, event, severity, details):
    """
    Save alert locally and publish to Hedera Consensus (best-effort).
    - user_id: int
    - event: short string
    - severity: e.g., "low", "medium", "high"
    - details: free-form dict or string (will be JSON-serialized)
    """
    # Normalize details
    details_json = details if isinstance(details, str) else json.dumps(details, default=str)

    # 1) Save locally (best-effort)
    alert_entry = None
    try:
        alert_entry = AlertLog(
            user_id=user_id,
            event=event,
            severity=severity,
            details=details_json,
            created_at=datetime.utcnow()
        )
        db.session.add(alert_entry)
        db.session.commit()
    except Exception as db_err:
        try:
            db.session.rollback()
        except Exception:
            pass
        print(f"[Alert Trigger] DB save failed: {db_err}")
        alert_entry = None

    # 2) Publish to Hedera Consensus (do not block on failure)
    try:
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "event": event,
            "severity": severity,
            "details": details if isinstance(details, (str, dict)) else str(details),
            "local_alert_id": getattr(alert_entry, "id", None)
        }
        res = publish_to_consensus(payload)
        if res.get("status") == "error":
            print(f"[Alert Trigger] Hedera publish returned error: {res}")
        return res
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[Alert Trigger] Hedera publish exception: {e}\n{tb}")
        return {"status": "error", "error": str(e), "traceback": tb}
