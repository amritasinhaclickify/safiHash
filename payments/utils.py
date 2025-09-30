# safichain/payments/utils.py
import os
import time
import base64
import requests

_MPESA_TOKEN_CACHE = {"token": None, "expires_at": 0}


def get_access_token():
    """
    Return cached access token, refresh if expired.
    Requires MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET in env.
    """
    now = int(time.time())
    if _MPESA_TOKEN_CACHE["token"] and _MPESA_TOKEN_CACHE["expires_at"] > now + 5:
        return _MPESA_TOKEN_CACHE["token"]

    key = os.getenv("MPESA_CONSUMER_KEY")
    secret = os.getenv("MPESA_CONSUMER_SECRET")
    env = os.getenv("MPESA_ENV", "sandbox")
    if not key or not secret:
        raise RuntimeError("MPESA_CONSUMER_KEY/SECRET not configured")

    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    if env == "sandbox":
        url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    else:
        url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

    headers = {"Authorization": f"Basic {auth}"}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3599))
    _MPESA_TOKEN_CACHE["token"] = token
    _MPESA_TOKEN_CACHE["expires_at"] = int(time.time()) + expires_in
    return token


def verify_mpesa_transaction(mpesa_ref: str, amount: float, msisdn: str) -> dict:
    """
    Verify a transaction by calling Daraja (or simulation).
    DARJA doesn't always provide a direct 'query by mpesa_ref' endpoint in sandbox;
    adapt to your provider. For sandbox we may use simulated responses or B2C query if supported.
    This function returns {"success": True, "raw": {...}} on success.
    """
    env = os.getenv("MPESA_ENV", "sandbox")
    token = get_access_token()

    # Example: If you have a transaction status endpoint (this is pseudo and may need adapting)
    try:
        if env == "sandbox":
            # For sandbox, if you don't have status endpoint, accept as verified if ref looks valid.
            # Better: keep sample payloads and compare.
            return {"success": True, "raw": {"mpesa_ref": mpesa_ref, "amount": amount, "msisdn": msisdn}}
        else:
            # Implement production verification here
            status_url = os.getenv("MPESA_STATUS_URL")  # set this in .env if available
            headers = {"Authorization": f"Bearer {token}"}
            payload = {"mpesa_ref": mpesa_ref, "amount": amount, "msisdn": msisdn}
            r = requests.post(status_url, json=payload, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            # parse according to your provider
            success = data.get("status") in ("Success", "Completed")
            return {"success": success, "raw": data}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Sandbox C2B simulate helper (uses Daraja sandbox simulate endpoint)
def simulate_c2b(msisdn: str, amount: float, order_id: str, shortcode: str = None):
    token = get_access_token()
    env = os.getenv("MPESA_ENV", "sandbox")
    shortcode = shortcode or os.getenv("MPESA_SHORTCODE")
    if not shortcode:
        raise RuntimeError("MPESA_SHORTCODE missing")
    if env == "sandbox":
        url = f"https://sandbox.safaricom.co.ke/mpesa/c2b/v1/simulate"
    else:
        url = f"https://api.safaricom.co.ke/mpesa/c2b/v1/simulate"

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "ShortCode": shortcode,
        "CommandID": "CustomerPayBillOnline",
        "Amount": int(amount),
        "Msisdn": msisdn,
        "BillRefNumber": order_id
    }
    r = requests.post(url, json=payload, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()
