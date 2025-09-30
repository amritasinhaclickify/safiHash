# hedera_sdk/wallet.py
from hedera import (
    AccountCreateTransaction,
    AccountBalanceQuery,
    AccountId,
    Hbar,
    PrivateKey,
    TokenId,
    TransferTransaction,
)
from .config import client
from . import token_service  # uses your real HTS functions
from extensions import db
from users.models import User
from jnius import autoclass
AccountId = autoclass("com.hedera.hashgraph.sdk.AccountId")


# ⬇️ NEW: transient timeout ke liye
import time
try:
    from jnius import JavaException
except Exception:
    # fallback: agar jnius import fail ho to generic Exception catch ho jayega
    class JavaException(Exception):
        pass


# ---------- FIXED: create & balance (normalized) ----------
def create_hedera_account(user_id: int | None = None, initial_balance: float = 10, metadata: dict | None = None):
    if not client:
        raise RuntimeError("Hedera client not initialized")

    last = None
    for i in range(3):  # 3 tries: 0s, 1s, 2s backoff on Timeout
        try:
            new_private_key = PrivateKey.generate()
            new_public_key = new_private_key.getPublicKey()

            tx = (
                AccountCreateTransaction()
                .setKey(new_public_key)
                .setInitialBalance(Hbar(initial_balance))
                .execute(client)
            )
            receipt = tx.getReceipt(client)  # yahi timeout throw kar sakta hai
            new_account_id = receipt.accountId

            # ✅ Normalize accountId string to avoid trailing zero issue
            normalized_account_id = AccountId.fromString(new_account_id.toString()).toString()

            # DB me persist (agar user_id diya gaya ho)
            if user_id is not None:
                user = User.query.get(user_id)
                if user:
                    user.hedera_account_id = normalized_account_id
                    user.hedera_private_key = new_private_key.toString()  # ✅ SAVE KEY
                    db.session.add(user)
                    db.session.commit()

    
            return {
                "user_id": user_id,
                "account_id": normalized_account_id,
                "private_key": new_private_key.toString(),
                "public_key": new_public_key.toString(),
                "metadata": metadata or {}
            }

        except JavaException as je:
            # Hedera Java SDK Timeout friendly retry
            if "TimeoutException" in str(je) and i < 2:
                time.sleep(i + 1)  # 1s, 2s
                last = je
                continue
            print("❌ Error creating Hedera account:", je)
            return None
        except Exception as e:
            print("❌ Error creating Hedera account:", e)
            return None


def fetch_wallet_balance(account_id: str) -> dict:
    if not client:
        raise RuntimeError("Hedera client not initialized")
    try:
        acc = AccountId.fromString(account_id)
        bal = AccountBalanceQuery().setAccountId(acc).execute(client)

        hbar = bal.hbars.toTinybars() / 1e8
        tokens = {}

        if hasattr(bal, "tokens") and bal.tokens is not None:
            try:
                # Java Map -> iterate using entrySet()
                for entry in bal.tokens.entrySet():
                    tid = entry.getKey().toString()
                    val = entry.getValue()
                    # Java Long safe extract
                    amt = val.longValue() if hasattr(val, "longValue") else int(val)
                    tokens[tid] = amt
            except Exception as e:
                print("⚠️ Token map parse error:", e)

        return {
            "account_id": account_id,
            "balance_hbar": hbar,
            "token_balances": tokens
        }
    except Exception as e:
        print("❌ Error fetching balance:", e)
        return {"account_id": account_id, "error": str(e)}


# ---------- NEW: HBAR transfer ----------
def transfer_hbar(from_account_id: str, from_private_key: str, to_account_id: str, amount_hbar: float) -> dict:
    """
    Move HBAR on-chain (e.g., fund new accounts, ops wallet funding, etc.).
    """
    if not client:
        raise RuntimeError("Hedera client not initialized")

    try:
        from_acc = AccountId.fromString(from_account_id)
        to_acc = AccountId.fromString(to_account_id)
        priv = PrivateKey.fromString(from_private_key)

        tx = (
            TransferTransaction()
            .addHbarTransfer(from_acc, Hbar(-abs(amount_hbar)))
            .addHbarTransfer(to_acc, Hbar(abs(amount_hbar)))
            .freezeWith(client)
        )
        signed = tx.sign(priv)
        resp = signed.execute(client)
        receipt = resp.getReceipt(client)

        return {
            "status": receipt.status.toString(),
            "tx_id": resp.transactionId.toString(),
            "from": from_account_id,
            "to": to_account_id,
            "amount_hbar": amount_hbar,
        }
    except Exception as e:
        return {"error": str(e)}


def ensure_token_ready_for_account(
    token_id: str,
    account_id: str,
    account_private_key: str,
    kyc_grant_signing_key: str,
) -> dict:
    """
    1) Associate the token to the account (retry-safe + idempotent).
    2) Grant KYC for that token to that account (retry with backoff).
    Returns dict: {"associate": <assoc_result>, "grant_kyc": True|False, "error": optional}
    """
    result = {"associate": None, "grant_kyc": None}

    # ---------- 1) Associate (retry-safe + idempotent) ----------
    last_assoc_err = None
    for attempt_num in range(3):  # 3 tries with backoff
        try:
            assoc = token_service.associate_token_with_account(
                token_id=token_id,
                account_id=account_id,
                account_privkey=account_private_key,
            )
            result["associate"] = assoc
            last_assoc_err = None
            break
        except Exception as e:
            msg = str(e)
            # If already associated, treat as success
            if "TOKEN_ALREADY_ASSOCIATED_TO_ACCOUNT" in msg or "ALREADY_ASSOCIATED" in msg:
                result["associate"] = "already"
                last_assoc_err = None
                break
            # Retry on transient errors
            if ("TimeoutException" in msg or "DUPLICATE_TRANSACTION" in msg) and attempt_num < 2:
                last_assoc_err = e
                time.sleep(attempt_num + 1)  # 1s, 2s
                continue
            # Non-transient: re-raise so caller can handle
            raise
    else:
        # loop exhausted without success
        result["associate"] = "failed"
        result["error"] = str(last_assoc_err) if last_assoc_err else "associate failed"
        return result

    # ---------- 2) Grant KYC (retry + verify) ----------
    last_err = None
    for attempt_num in range(3):
        try:
            kyc = token_service.grant_kyc(
                token_id=token_id,
                account_id=account_id,
                operator_privkey=kyc_grant_signing_key,
            )
            # normalize different return shapes:
            if hasattr(kyc, "status") and str(kyc.status).upper().endswith("SUCCESS"):
                result["grant_kyc"] = True
                return result
            if isinstance(kyc, dict) and str(kyc.get("status", "")).upper().endswith("SUCCESS"):
                result["grant_kyc"] = True
                return result

            # If token_service returns something else, treat as transient failure and retry
            last_err = f"Unexpected grant_kyc response: {kyc}"
        except Exception as e:
            msg = str(e)
            # Retry on transient issues reported by JVM / network
            if ("TimeoutException" in msg or "DUPLICATE_TRANSACTION" in msg) and attempt_num < 2:
                last_err = e
                time.sleep(attempt_num + 1)
                continue
            # For idempotent errors like already granted, accept as success
            if "KYC_ALREADY_GRANTED" in msg or "ALREADY_KYC_GRANTED" in msg:
                result["grant_kyc"] = True
                return result
            last_err = e
        # backoff before next attempt
        time.sleep(attempt_num + 1)

    # All KYC attempts failed
    result["grant_kyc"] = False
    result["error"] = str(last_err)
    return result




# ---------- NEW: helper to fetch ONE token’s balance cleanly ----------
def fetch_single_token_balance(account_id: str, token_id: str) -> int | None:
    """
    Returns raw token units (respect your token's decimals separately).
    """
    info = fetch_wallet_balance(account_id)
    if "token_balances" not in info or not isinstance(info["token_balances"], dict):
        return None
    # token_id can be string; normalize keys
    for tid, amt in info["token_balances"].items():
        if tid == token_id or TokenId.fromString(tid).toString() == TokenId.fromString(token_id).toString():
            return int(amt)
    return None

