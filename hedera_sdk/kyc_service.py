# hedera_sdk/kyc_service.py
import hashlib
import os
from hedera import (
    Client,
    FileCreateTransaction,
    FileContentsQuery,
    Hbar,
    PrivateKey,
    AccountId
)
import traceback
from jnius import autoclass

# Java SDK classes (via jnius)
FileCreateTransaction = autoclass("com.hedera.hashgraph.sdk.FileCreateTransaction")
FileContentsQuery = autoclass("com.hedera.hashgraph.sdk.FileContentsQuery")
Hbar = autoclass("com.hedera.hashgraph.sdk.Hbar")
PrivateKey = autoclass("com.hedera.hashgraph.sdk.PrivateKey")
# Key class and Key[] array type
Key = autoclass("com.hedera.hashgraph.sdk.Key")
KeyArray = autoclass("[Lcom.hedera.hashgraph.sdk.Key;")
# ---------------- In-Memory KYC State ----------------
_KYC_STATE: dict[int, bool] = {}

def set_kyc_status(user_id: int, approved: bool) -> dict:
    _KYC_STATE[user_id] = bool(approved)
    return {"user_id": user_id, "approved": _KYC_STATE[user_id]}

def is_kyc_approved(user_id: int) -> bool:
    return _KYC_STATE.get(user_id, False)


# ---------------- Hedera Client Setup ----------------
HEDERA_OPERATOR_ID   = os.getenv("HEDERA_OPERATOR_ID")
HEDERA_OPERATOR_KEY  = os.getenv("HEDERA_OPERATOR_KEY")

_client = None
if HEDERA_OPERATOR_ID and HEDERA_OPERATOR_KEY:
    _client = Client.forTestnet()   # ✅ correct method
    _client.setOperator(
        AccountId.fromString(HEDERA_OPERATOR_ID),
        PrivateKey.fromString(HEDERA_OPERATOR_KEY)
    )



# ---------------- File Upload & Verify ----------------
def upload_to_hfs(file_path: str) -> dict:
    """
    Upload a file to Hedera File Service using Java-binding SDK (jnius).
    Returns: {"file_id": "<string>", "hash": "<sha256 hex>"} on success.
    """
    if not globals().get("_client"):
        raise RuntimeError("Hedera client not initialized")

    try:
        # Read file bytes and compute SHA256
        with open(file_path, "rb") as f:
            data = f.read()
        file_hash = hashlib.sha256(data).hexdigest()

        # Build operator public key (Java PrivateKey -> PublicKey)
        op_priv = PrivateKey.fromString(HEDERA_OPERATOR_KEY)
        op_pub = op_priv.getPublicKey()

        # Create FileCreateTransaction and execute
        tx = (FileCreateTransaction()
              .setKeys(op_pub)
              .setContents(data)
              .setMaxTransactionFee(Hbar(2)))  # adjust fee if needed

        resp = tx.execute(_client)
        receipt = resp.getReceipt(_client)

        # Convert Java FileId -> plain Python string (e.g. "0.0.1234")
        try:
            file_id_str = receipt.fileId.toString()
        except Exception:
            # fallback: coerce and strip wrapper if needed
            file_id_str = str(receipt.fileId)
            # if still looks like a jnius wrapper, try extracting digits
            if "FileId" in file_id_str and "0.0." in file_id_str:
                import re
                m = re.search(r"(0\.0\.\d+)", file_id_str)
                if m:
                    file_id_str = m.group(1)

        # Ensure Python string
        file_id_str = str(file_id_str)

        return {"file_id": file_id_str, "hash": file_hash}

    except Exception as exc:
        tb = traceback.format_exc()
        raise RuntimeError(f"Hedera upload failed: {exc}\n{tb}")



def verify_file_hash(file_id: str, expected_hash: str) -> bool:
    """
    Fetch file contents from HFS and verify SHA256 matches expected_hash.
    `file_id` may be a string like '0.0.1234' or the Java FileId string representation.
    """
    if not globals().get("_client"):
        raise RuntimeError("Hedera client not initialized")

    try:
        # Convert string -> Java FileId object (works with both "0.0.x" and Java str form)
        fid = None
        try:
            fid = FileId.fromString(file_id)
        except Exception:
            # fallback: if fromString fails, try to build by parsing numeric parts (best-effort)
            fid = FileId.fromString(file_id)

        contents = FileContentsQuery().setFileId(fid).execute(_client)
        # contents is bytes; compute sha256
        file_hash = hashlib.sha256(contents).hexdigest()
        return file_hash == expected_hash
    except Exception as exc:
        tb = traceback.format_exc()
        raise RuntimeError(f"Hedera file verify failed: {exc}\n{tb}")







