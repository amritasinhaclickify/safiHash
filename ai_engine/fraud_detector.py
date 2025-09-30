# ai_engine/fraud_detector.py

def is_suspicious_transaction(txn: dict) -> bool:
    """
    Basic rule-based fraud detection.
    You can later replace this with AI/ML logic.
    """
    amount = txn.get("amount", 0)
    location = txn.get("location", "").lower()

    if amount > 10000:
        return True
    if "nigeria" in location and amount > 5000:
        return True

    return False


def detect_fraud(user_data: dict) -> dict:
    """
    Simple rule-based fraud scoring on user behavior.
    """

    alerts = []

    if user_data.get("login_attempts", 0) > 5:
        alerts.append("Too many login attempts")
    
    if user_data.get("loan_defaults", 0) > 3:
        alerts.append("Multiple loan defaults")
    
    if not user_data.get("kyc_verified", False):
        alerts.append("KYC not verified")

    is_fraud = len(alerts) > 0

    return {
        "is_fraud": is_fraud,
        "alerts": alerts
    }
