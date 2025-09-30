# hedera_sdk/token_service.py

from hedera import (
    TokenCreateTransaction,
    TokenType,
    TokenSupplyType,
    TokenAssociateTransaction,
    TokenGrantKycTransaction,
    TokenMintTransaction,
    TransferTransaction,
    Hbar,
    AccountId,
    PrivateKey,
    TokenId,  # ensure TokenId is imported
)
from .config import client

# ✅ PyJNIus helpers & retry backoff
from jnius import autoclass, JavaException
import time

# ✅ TransactionId generator (for fresh tx id per attempt)
TransactionId = autoclass('com.hedera.hashgraph.sdk.TransactionId')


# ---------------- Fungible Token ----------------
def create_token_for_group(group_name: str, treasury_account: str, treasury_key: str) -> dict:
    if not client:
        raise RuntimeError("Hedera client not initialized")

    treasury_acc = AccountId.fromString(treasury_account)
    treasury_priv = PrivateKey.fromString(treasury_key)
    treasury_pub = treasury_priv.getPublicKey()

    tx = (
        TokenCreateTransaction()
        .setTokenName(group_name)
        .setTokenSymbol(group_name[:3].upper())
        .setTreasuryAccountId(treasury_acc)
        .setInitialSupply(0)
        .setDecimals(2)
        .setTokenType(TokenType.FUNGIBLE_COMMON)
        .setSupplyType(TokenSupplyType.INFINITE)
        .setSupplyKey(treasury_pub)
        .setKycKey(treasury_pub)
        .setAdminKey(treasury_pub)
        .execute(client)
    )

    receipt = tx.getReceipt(client)
    return {"token_id": receipt.tokenId.toString(), "name": group_name}


def associate_token_with_account(token_id: str, account_id: str, account_privkey: str) -> dict:
    if not client:
        raise RuntimeError("Hedera client not initialized")

    acc = AccountId.fromString(account_id)
    priv = PrivateKey.fromString(account_privkey)
    tid = TokenId.fromString(token_id)

    # ✅ Java List<TokenId> use karo
    Arrays = autoclass('java.util.Arrays')
    token_list = Arrays.asList(tid)

    tx = (
        TokenAssociateTransaction()
        .setAccountId(acc)
        .setTokenIds(token_list)
        .freezeWith(client)
    )
    signed = tx.sign(priv)

    last = None
    for i in range(3):
        try:
            resp = signed.execute(client)
            receipt = resp.getReceipt(client)
            return {
                "status": receipt.status.toString(),
                "tx_id": resp.transactionId.toString(),
                "account_id": account_id,
                "token_id": token_id,
            }
        except JavaException as je:
            if "TimeoutException" in str(je) and i < 2:
                time.sleep(1 + i)
                last = je
                continue
            raise

    raise RuntimeError(f"Association failed after retries: {str(last)[:200] if last else 'unknown error'}")


def grant_kyc(token_id: str, account_id: str, operator_privkey: str) -> dict:
    if not client:
        raise RuntimeError("Hedera client not initialized")

    acc = AccountId.fromString(account_id)
    priv = PrivateKey.fromString(operator_privkey)
    tid = TokenId.fromString(token_id)

    tx = TokenGrantKycTransaction().setAccountId(acc).setTokenId(tid).freezeWith(client)
    signed = tx.sign(priv)
    resp = signed.execute(client)
    receipt = resp.getReceipt(client)

    return {"status": receipt.status.toString(), "account_id": account_id, "token_id": token_id}


def mint_tokens(token_id: str, amount: int, treasury_privkey: str) -> dict:
    if not client:
        raise RuntimeError("Hedera client not initialized")

    priv = PrivateKey.fromString(treasury_privkey)
    tx = TokenMintTransaction().setTokenId(TokenId.fromString(token_id)).setAmount(amount).freezeWith(client)
    signed = tx.sign(priv)
    resp = signed.execute(client)
    receipt = resp.getReceipt(client)

    return {"status": receipt.status.toString(), "token_id": token_id, "minted": amount}


def transfer_hts_token(token_id: str, from_account: str, from_privkey: str, to_account: str, amount: int) -> dict:
    """
    Token transfer with retry. Har attempt par fresh TransactionId + fresh sign.
    """
    if not client:
        raise RuntimeError("Hedera client not initialized")

    from_acc = AccountId.fromString(from_account)
    to_acc = AccountId.fromString(to_account)
    priv = PrivateKey.fromString(from_privkey)
    tid = TokenId.fromString(token_id)

    last = None
    for i in range(5):
        # ✅ NAYA tx + NAYA TransactionId + freeze + sign (loop ke andar)
        tx = (
            TransferTransaction()
            .addTokenTransfer(tid, from_acc, -int(amount))
            .addTokenTransfer(tid, to_acc,   int(amount))
            .setTransactionId(TransactionId.generate(client.getOperatorAccountId()))
            .freezeWith(client)
        )
        signed = tx.sign(priv)
        try:
            resp = signed.execute(client)
            receipt = resp.getReceipt(client)
            return {
                "status": receipt.status.toString(),
                "from": from_account,
                "to": to_account,
                "token_id": token_id,
                "amount": amount,
                "tx_id": resp.transactionId.toString(),
            }
        except JavaException as je:
            msg = str(je)
            if (("DUPLICATE_TRANSACTION" in msg) or ("TimeoutException" in msg)) and i < 2:
                time.sleep(1 + i)
                last = je
                continue
            raise


# ---------------- NFT (Non-Fungible Token) ----------------
def create_nft_token(name: str, symbol: str, treasury_account: str, treasury_key: str) -> dict:
    if not client:
        raise RuntimeError("Hedera client not initialized")

    treasury_acc = AccountId.fromString(treasury_account)
    treasury_priv = PrivateKey.fromString(treasury_key)
    treasury_pub = treasury_priv.getPublicKey()

    tx = (
        TokenCreateTransaction()
        .setTokenName(name)
        .setTokenSymbol(symbol)
        .setTreasuryAccountId(treasury_acc)
        .setTokenType(TokenType.NON_FUNGIBLE_UNIQUE)
        .setSupplyType(TokenSupplyType.INFINITE)
        .setSupplyKey(treasury_pub)
        .setKycKey(treasury_pub)
        .setAdminKey(treasury_pub)
        .execute(client)
    )

    receipt = tx.getReceipt(client)
    return {"nft_token_id": receipt.tokenId.toString(), "name": name}


def mint_nft_for_user(nft_token_id: str, treasury_privkey: str, metadata: dict) -> dict:
    if not client:
        raise RuntimeError("Hedera client not initialized")

    import json
    metadata_bytes = json.dumps(metadata).encode("utf-8")
    priv = PrivateKey.fromString(treasury_privkey)
    tid = TokenId.fromString(nft_token_id)

    tx = TokenMintTransaction().setTokenId(tid).setMetadata([metadata_bytes]).freezeWith(client)
    signed = tx.sign(priv)
    resp = signed.execute(client)
    receipt = resp.getReceipt(client)

    return {
        "status": receipt.status.toString(),
        "nft_token_id": nft_token_id,
        "serial": receipt.serials[0].toInt(),
        "metadata": metadata,
    }


# ---------------- KYC Badge Utility ----------------
def assign_kyc_token(user_id: int):
    return {"status": "ok", "user_id": user_id, "message": "KYC NFT assigned"}


# ---------------- Unified Transfer Utility ----------------
def transfer_asset(
    asset_type: str,       # "HBAR" or "BHC"
    sender_account: str,
    sender_privkey: str,
    recipient_account: str,
    amount: float,
    token_id: str = None
) -> dict:
    if asset_type.upper() == "HBAR":
        from .transfer import transfer_hbar
        return transfer_hbar(
            sender_account=sender_account,
            sender_key=sender_privkey,
            recipient_account=recipient_account,
            amount_hbar=amount
        )
    elif asset_type.upper() == "BHC":
        if not token_id:
            raise ValueError("token_id required for BHC transfer")
        return transfer_hts_token(
            token_id=token_id,
            from_account=sender_account,
            from_privkey=sender_privkey,
            to_account=recipient_account,
            amount=int(amount)
        )
    else:
        raise ValueError("Unsupported asset_type, use 'HBAR' or 'BHC'")


def setup_bhc_token(treasury_account: str, treasury_key: str) -> dict:
    return create_token_for_group("BHCoin", treasury_account, treasury_key)
