# utils/reminder_service.py
from datetime import datetime, timedelta
from finance.models import Loan
from notifications.models import Notification
from extensions import db

# Hedera Schedule Service import
try:
    from hedera_sdk.schedule_service import schedule_reminder_job
except ImportError:
    def schedule_reminder_job(job_name, run_at_iso, payload):
        print(f"[Hedera Dummy] Job: {job_name}, Run At: {run_at_iso}, Payload: {payload}")
        return {"status": "scheduled", "job": job_name, "run_at": run_at_iso}

def send_repayment_reminders():
    """
    Find loans due in next 3 days, send DB notifications,
    and also schedule them on Hedera for immutable tracking.
    """
    today = datetime.utcnow()
    upcoming_loans = Loan.query.filter(
        Loan.status == 'approved',
        Loan.next_due_date <= today + timedelta(days=3)
    ).all()

    reminders_sent = []

    for loan in upcoming_loans:
        due_date_str = loan.next_due_date.strftime('%Y-%m-%d')
        message = f"Reminder: Your EMI for Loan ID {loan.id} is due on {due_date_str}."
        
        # ---- 1) Save to Notification table ----
        notif = Notification(user_id=loan.user_id, message=message)
        db.session.add(notif)
        reminders_sent.append(message)

        # ---- 2) Schedule on Hedera ----
        try:
            schedule_reminder_job(
                job_name=f"loan_reminder_{loan.id}",
                run_at_iso=loan.next_due_date.isoformat(),
                payload={
                    "loan_id": loan.id,
                    "user_id": loan.user_id,
                    "due_date": due_date_str,
                    "message": message
                }
            )
        except Exception as e:
            print(f"[Reminder Service] Failed to schedule reminder on Hedera: {e}")

    db.session.commit()
    return reminders_sent
