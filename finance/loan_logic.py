from finance.models import Loan, Wallet, TransactionHistory, db
from datetime import datetime
from utils.alert_trigger import trigger_alert

def disburse_loan(loan_id):
    loan = Loan.query.get(loan_id)
    if not loan or loan.status != 'approved':
        return {"error": "Loan not found or not approved"}, 400

    wallet = Wallet.query.filter_by(user_id=loan.user_id).first()
    if not wallet:
        return {"error": "Wallet not found"}, 404

    # Update wallet balance
    wallet.balance += loan.amount
    loan.status = 'disbursed'

    # Record transaction
    transaction = TransactionHistory(
        user_id=loan.user_id,
        type='disbursement',  # ✅ Fixed field name
        amount=loan.amount,
        timestamp=datetime.utcnow()
    )

    db.session.add(transaction)
    db.session.add(loan)  # ✅ Optional but recommended
    db.session.commit()

    return {"message": "Loan disbursed successfully", "new_balance": wallet.balance}, 200



def detect_tampering(user_id):
    trigger_alert(
        user_id=user_id,
        event="Tampering Detected",
        severity="high",
        details="Manual override of loan status without vote count."
    )

