# mpesa_test.py
import os
from payments.utils import simulate_c2b
from dotenv import load_dotenv

# .env load karo
load_dotenv()

# Sandbox ke 10 virtual MSISDNs (example list)
VIRTUAL_MSISDNS = [
    "254700000001",
    "254700000002",
    "254700000003",
    "254700000004",
    "254700000005",
    "254700000006",
    "254700000007",
    "254700000008",
    "254700000009",
    "254700000010",
]

def main():
    print("🚀 M-Pesa sandbox C2B simulation starting...\n")
    for i, msisdn in enumerate(VIRTUAL_MSISDNS, start=1):
        order_id = f"testorder{i:02d}"
        amount = 10 + i  # vary amounts (11, 12, ...)
        try:
            res = simulate_c2b(msisdn=msisdn, amount=amount, order_id=order_id)
            print(f"[{i}] MSISDN={msisdn}, Amount={amount}, Order={order_id}")
            print("   Response:", res, "\n")
        except Exception as e:
            print(f"[{i}] ❌ Failed for {msisdn}: {e}")

if __name__ == "__main__":
    main()
