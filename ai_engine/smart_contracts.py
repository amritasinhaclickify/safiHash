from datetime import datetime, timedelta
import random

def disburse_loan(user_id: int, amount: float, duration_months: int = 12):
    """
    Simulates smart contract logic for loan disbursal:
    - Sets up EMI schedule
    - Marks loan as active
    """
    emi_amount = round(amount / duration_months, 2)
    today = datetime.utcnow()
    emi_schedule = []

    for i in range(duration_months):
        due_date = today + timedelta(days=30 * (i + 1))
        emi_schedule.append({
            "month": i + 1,
            "due_date": due_date.strftime("%Y-%m-%d"),
            "amount": emi_amount,
            "status": "pending"
        })

    contract_result = {
        "user_id": user_id,
        "loan_amount": amount,
        "emi_amount": emi_amount,
        "duration_months": duration_months,
        "schedule": emi_schedule,
        "status": "active"
    }

    return contract_result


def process_repayment(user_id: int, emi_paid: float, due: float):
    """
    Simulates repayment logic & returns reward or penalty.
    """
    if emi_paid >= due:
        return {
            "status": "paid",
            "message": "✅ EMI paid on time. Reward credited.",
            "reward_points": random.randint(5, 15)
        }
    else:
        return {
            "status": "late",
            "message": "⚠️ EMI paid late. Penalty applied.",
            "penalty": round(due - emi_paid, 2)
        }
