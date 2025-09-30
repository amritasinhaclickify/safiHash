# finance/loan.py

from finance.models import db, Loan
from hedera_sdk.smart_contracts import trigger_loan_disbursement

def process_loan(user_id: int, amount: float, purpose: str) -> dict:
    # Create loan entry
    loan = Loan(user_id=user_id, amount=amount, purpose=purpose, status='approved')
    db.session.add(loan)
    db.session.commit()

    # Simulate smart contract disbursal
    success = trigger_loan_disbursement(user_id, amount)
    loan.status = 'disbursed' if success else 'failed'
    db.session.commit()

    return {
        "loan_id": loan.id,
        "status": loan.status
    }
