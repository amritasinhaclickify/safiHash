# hedera_sdk/smart_contracts.py
"""
Simplified smart contract stubs for 1–5 normal flow.
No real contract calls — just placeholders so imports don't break.
"""

# ---------------- CREATE LOAN ----------------
def create_loan_onchain(token_address, vault_address, amount, sender=None, priv=None):
    """
    Stub: In normal 1–5 flow, loan creation is DB-only.
    This returns a fake tx hash for compatibility.
    """
    return {"status": "success", "tx_hash": f"fake_create_tx_{amount}"}


# ---------------- REPAY LOAN ----------------
def repay_loan_onchain(token_address, vault_address, loan_id, amount, sender=None, priv=None):
    """
    Stub: In normal 1–5 flow, repayment is DB-only.
    This returns a fake tx hash for compatibility.
    """
    return {"status": "success", "tx_hash": f"fake_repay_tx_{loan_id}_{amount}"}


# ---------------- GET LOAN ----------------
def get_loan_onchain(loan_id):
    """
    Stub: In normal 1–5 flow, loan details are tracked in DB.
    """
    return {
        "loan_id": loan_id,
        "status": "approved",
        "principal": 0,
        "repaid": 0,
        "fake": True,
    }
