# hedera_sdk/contracts.py
import os
import json
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ----------------
HEDERA_RPC_URL = "https://testnet.hashio.io/api"   # Hedera JSON-RPC relay
w3 = Web3(Web3.HTTPProvider(HEDERA_RPC_URL))

# ENV keys
PRIVATE_KEY = os.getenv("HEDERA_EVM_PRIVATE_KEY")   # ✅ .env me dalna hoga
OWNER_ADDR = None
if PRIVATE_KEY:
    acct = Account.from_key(PRIVATE_KEY)
    OWNER_ADDR = acct.address

# ABI & Bytecode (Remix compile karke artifacts folder me save karo)
ABI_PATH = os.path.join("contracts", "build", "CoopTrust.abi.json")
BIN_PATH = os.path.join("contracts", "build", "CoopTrust.bin.json")

with open(ABI_PATH) as f:
    COOPTRUST_ABI = json.load(f)

with open(BIN_PATH) as f:
    COOPTRUST_BYTECODE = json.load(f)["object"]

# ---------------- HELPERS ----------------
def _sign_and_send(tx):
    """Signs and sends a transaction, waits for receipt"""
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
    tx_hash = w3.eth.send_raw_transaction(raw_tx)
    return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)


# ---------------- DEPLOY ----------------
def deploy_cooptrust():
    """Deploy CoopTrust contract with OWNER as admin"""
    contract = w3.eth.contract(abi=COOPTRUST_ABI, bytecode=COOPTRUST_BYTECODE)

    construct_txn = contract.constructor(OWNER_ADDR).build_transaction({
        "from": OWNER_ADDR,
        "nonce": w3.eth.get_transaction_count(OWNER_ADDR),
        "gas": 3_000_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": 296   # ✅ Hedera Testnet chainId
    })
    receipt = _sign_and_send(construct_txn)
    return {
        "contractAddress": receipt.contractAddress,
        "txHash": receipt.transactionHash.hex()
    }

# ---------------- INSTANCE ----------------
def get_cooptrust_instance(address):
    """Return CoopTrust contract instance"""
    return w3.eth.contract(address=address, abi=COOPTRUST_ABI)

# ---------------- TRUST SCORE UPDATE (emit event) ----------------
def emit_trust_score(contract_addr, user_id, group_id, score_x100, note=""):
    """
    Calls setTrustScore on CoopTrust smart contract.
    - score_x100 = trust score * 100 (0–10000)
    - user_id, group_id should be int
    - note = string reason
    """
    try:
        # clamp score to 0–10000 (0–100 * 100)
        score_x100 = max(0, min(int(score_x100), 10000))

        if not OWNER_ADDR or not PRIVATE_KEY:
            return {"status": "error", "error": "Missing OWNER private key in env"}

        contract = get_cooptrust_instance(contract_addr)

        tx = contract.functions.setTrustScore(
            int(user_id), int(group_id or 0), score_x100, note or ""
        ).build_transaction({
            "from": OWNER_ADDR,
            "nonce": w3.eth.get_transaction_count(OWNER_ADDR),
            "gas": 200_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": 296   # ✅ Hedera Testnet chainId
        })

        receipt = _sign_and_send(tx)
        return {
            "status": "success" if receipt.status == 1 else "failed",
            "txHash": receipt.transactionHash.hex(),
            "blockNumber": receipt.blockNumber,
            "gasUsed": receipt.gasUsed
        }

    except Exception as e:
        print("⚠️ emit_trust_score failed:", str(e))
        return {"status": "error", "error": str(e)}
