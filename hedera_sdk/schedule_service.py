# hedera_sdk/schedule_service.py
from datetime import datetime

def schedule_reminder_job(job_name: str, run_at_iso: str, payload: dict) -> dict:
    """
    Placeholder: Real में ScheduleCreateTransaction.
    """
    # सिर्फ़ response; कोई persistent scheduler नहीं (MVP)
    return {
        "status": "scheduled",
        "job": job_name,
        "run_at": run_at_iso,
        "payload": payload,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
