# hedera_sdk/transfer.py
import os
from dataclasses import dataclass
from typing import Dict, Any

from hedera import (
    Client,
    AccountId,
    PrivateKey,
    Hbar,
    TransferTransaction,
)

# ---- Config from ENV (.env via python-dotenv or your Config class) ----
HEDERA_OPERATOR_ID = os.getenv("HEDERA_OPERATOR_ID")
HEDERA_OPERATOR_KEY = os.getenv("HEDERA_OPERATOR_KEY")
PRODUCTION = (os.getenv("PRODUCTION", "false").strip().lower() == "true")


# Small compatibility helpers (SDK versions differ a bit in method names)
def _from_tinybars(tinybars: int):
    try:
        return Hbar.from_tinybars(tinybars)  # pythonic
    except AttributeError:
        return Hbar.fromTinybars(tinybars)   # camelCase (older sigs)


def _add_hbar_transfer(tx: TransferTransaction, account: AccountId, hbar: Hbar):
    try:
        return tx.add_hbar_transfer(account, hbar)  # pythonic
    except AttributeError:
        return tx.addHbarTransfer(account, hbar)    # camelCase


def _freeze_with(tx: TransferTransaction, client: Client):
    try:
        return tx.freeze_with(client)  # pythonic
    except AttributeError:
        return tx.freezeWith(client)   # camelCase


def _get_receipt(resp, client: Client):
    try:
        return resp.get_receipt(client)  # pythonic
    except AttributeError:
        return resp.getReceipt(client)   # camelCase


def _tx_id_str(tx: TransferTransaction) -> str:
    # different SDKs expose as .transaction_id / .transactionId
    tid = getattr(tx, "transaction_id", None) or getattr(tx, "transactionId", None)
    return str(tid)


@dataclass
class HederaResult:
    transaction_id: str
    status: str
    path: list[str]


def get_client() -> Client:
    """Return a Hedera client for Testnet/Mainnet and set operator from ENV."""
    client = Client.forMainnet() if PRODUCTION else Client.forTestnet()
    if not HEDERA_OPERATOR_ID or not HEDERA_OPERATOR_KEY:
        raise RuntimeError("HEDERA_OPERATOR_ID/HEDERA_OPERATOR_KEY not set in environment")

    client.setOperator(AccountId.fromString(HEDERA_OPERATOR_ID),
                   PrivateKey.fromString(HEDERA_OPERATOR_KEY))
    return client


def transfer_hbar(
    sender_account: str,
    sender_key: str,
    recipient_account: str,
    amount_hbar: float,
    memo: str | None = None,   # ✅ optional memo
) -> Dict[str, Any]:
    """
    REAL HBAR transfer on Hedera.
    Returns a normalized dict with both `transaction_id` and `tx_id`.
    """
    if amount_hbar <= 0:
        raise ValueError("amount_hbar must be > 0")

    client = get_client()

    sender_id    = AccountId.fromString(sender_account)
    recipient_id = AccountId.fromString(recipient_account)
    priv         = PrivateKey.fromString(sender_key)

    # ✅ precise tinybars conversion
    tiny = int(round(float(amount_hbar) * 100_000_000))

    tx = TransferTransaction()
    _add_hbar_transfer(tx, sender_id, _from_tinybars(-tiny))
    _add_hbar_transfer(tx, recipient_id, _from_tinybars(tiny))

    # ✅ optional memo (SDK variants)
    if memo:
        try:
            tx.set_transaction_memo(memo)
        except AttributeError:
            try:
                tx.setTransactionMemo(memo)
            except Exception:
                pass

    _freeze_with(tx, client)
    tx = tx.sign(priv)
    resp = tx.execute(client)
    receipt = _get_receipt(resp, client)

    tid = _tx_id_str(tx)
    return {
        "transaction_id": tid,            # canonical
        "tx_id": tid,                     # alias (for callers using tx_id)
        "status": str(receipt.status),
        "path": [str(sender_id), str(recipient_id)],
    }

