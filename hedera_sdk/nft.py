# hedera_sdk/nft.py
import os
from dotenv import load_dotenv

from hedera import (
    Client,
    AccountId,
    PrivateKey,
    TokenMintTransaction,
    TransferTransaction,
    TokenId,
)

# ---- Load ENV ----
load_dotenv()
HEDERA_OPERATOR_ID = os.getenv("HEDERA_OPERATOR_ID")
HEDERA_OPERATOR_KEY = os.getenv("HEDERA_OPERATOR_KEY")
KYC_NFT_ID = os.getenv("KYC_NFT_ID")
PRODUCTION = (os.getenv("PRODUCTION", "false").lower() == "true")


def get_client() -> Client:
    """Return a Hedera client for Testnet/Mainnet with operator set."""
    client = Client.forMainnet() if PRODUCTION else Client.forTestnet()
    if not HEDERA_OPERATOR_ID or not HEDERA_OPERATOR_KEY:
        raise RuntimeError("HEDERA_OPERATOR_ID/HEDERA_OPERATOR_KEY not set in env")

    client.setOperator(
        AccountId.fromString(HEDERA_OPERATOR_ID),
        PrivateKey.fromString(HEDERA_OPERATOR_KEY),
    )
    return client


def mint_nft(metadata: bytes, token_id: str = None):
    """
    Mint an NFT into the collection.
    - metadata: should be bytes (e.g. b'kyc-verified:user123')
    - token_id: NFT collection token ID (default from .env: KYC_NFT_ID)
    Returns: receipt with status
    """
    if token_id is None:
        token_id = KYC_NFT_ID
    if not token_id:
        raise ValueError("NFT token ID must be provided (or set KYC_NFT_ID in .env)")

    client = get_client()
    token = TokenId.fromString(token_id)

    tx = TokenMintTransaction().setTokenId(token).addMetadata(metadata)
    resp = tx.execute(client)
    receipt = resp.getReceipt(client)

    return {
        "status": str(receipt.status),
        "serials": [s.toString() for s in receipt.serials],
    }


def transfer_nft(sender: str, sender_key: str, recipient: str, serial: int, token_id: str = None):
    """
    Transfer a minted NFT from one account to another.
    """
    if token_id is None:
        token_id = KYC_NFT_ID
    if not token_id:
        raise ValueError("NFT token ID must be provided (or set KYC_NFT_ID in .env)")

    client = get_client()
    priv = PrivateKey.fromString(sender_key)
    token = TokenId.fromString(token_id)

    tx = TransferTransaction().addNftTransfer(token, serial, sender, recipient)
    tx = tx.freezeWith(client).sign(priv)

    resp = tx.execute(client)
    receipt = resp.getReceipt(client)

    return {
        "status": str(receipt.status),
        "from": sender,
        "to": recipient,
        "serial": serial,
    }
