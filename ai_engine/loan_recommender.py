# ai_engine/loan_recommender.py

def recommend_loan(user_data: dict) -> dict:
    """
    AI-based logic to recommend loan based on user's trust score and history.
    """

    trust_score = user_data.get("trust_score", 0)
    on_time_payments = user_data.get("on_time_payments", 0)
    loan_defaults = user_data.get("loan_defaults", 0)

    if trust_score >= 85:
        return {
            "amount": 10000,
            "interest_rate": "5%",
            "duration": "12 months",
            "recommendation": "Excellent! Eligible for premium loan."
        }
    elif trust_score >= 60:
        return {
            "amount": 5000,
            "interest_rate": "10%",
            "duration": "8 months",
            "recommendation": "Good! Eligible for standard loan."
        }
    elif trust_score >= 40:
        return {
            "amount": 2000,
            "interest_rate": "15%",
            "duration": "6 months",
            "recommendation": "Fair. Eligible for limited loan."
        }
    else:
        return {
            "amount": 0,
            "recommendation": "Sorry, not eligible for a loan at this time."
        }
