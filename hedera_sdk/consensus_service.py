# hedera_sdk/consensus_service.py
import os
import json
from datetime import datetime
import requests
from hedera import (
    TopicCreateTransaction,
    TopicMessageSubmitTransaction,
    TopicId
)
from .config import client, get_config

# 🔑 Load once from .env at module import
_DEFAULT_TOPIC_ID: TopicId | None = None
if os.getenv("HEDERA_TOPIC_ID"):
    _DEFAULT_TOPIC_ID = TopicId.fromString(os.getenv("HEDERA_TOPIC_ID"))


def create_consensus_topic(memo: str = "KYC_AUDIT_LOGS") -> str:
    """
    Ek naya HCS Topic banata hai.
    Iska topic_id save karlo DB ya env me, baar-baar create mat karo.
    """
    if not client:
        raise RuntimeError("Hedera client not initialized")

    tx = TopicCreateTransaction().setTopicMemo(memo).execute(client)
    receipt = tx.getReceipt(client)
    topic_id = receipt.topicId.toString()

    global _DEFAULT_TOPIC_ID
    _DEFAULT_TOPIC_ID = TopicId.fromString(topic_id)

    print(f"✅ Consensus Topic created: {topic_id}")
    return topic_id


def publish_to_consensus(message: dict | str, topic_id: str | None = None) -> dict:
    """
    Message ko Hedera Consensus Service (HCS) par publish karega.
    """
    if not client:
        raise RuntimeError("Hedera client not initialized")

    global _DEFAULT_TOPIC_ID
    if topic_id:
        topic = TopicId.fromString(topic_id)
    elif _DEFAULT_TOPIC_ID:
        topic = _DEFAULT_TOPIC_ID
    else:
        raise RuntimeError("No TopicId available. Call create_consensus_topic() first or pass topic_id.")

    # Message ko string bana do
    message_str = json.dumps(message) if not isinstance(message, str) else message

    tx = (
        TopicMessageSubmitTransaction()
        .setTopicId(topic)
        .setMessage(message_str)
        .execute(client)
    )
    receipt = tx.getReceipt(client)

    return {
        "status": "ok",
        "topic_id": topic.toString(),
        "consensus_ts": datetime.utcnow().isoformat() + "Z",
        "message": message_str,
        "sequence": receipt.topicSequenceNumber
    }


def fetch_topic_messages(topic_id: str, limit: int = 10) -> list[dict]:
    """
    Hedera Mirror Node se recent messages fetch karta hai.
    """
    cfg = get_config()
    url = f"{cfg.mirror_node_url}/api/v1/topics/{topic_id}/messages?order=desc&limit={limit}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        messages = []
        for m in data.get("messages", []):
            try:
                decoded = (
                    bytes.fromhex(m["message"]).decode("utf-8")
                    if "message" in m else None
                )
                parsed = json.loads(decoded) if decoded else None
            except Exception:
                decoded = None
                parsed = None

            messages.append({
                "consensus_ts": m.get("consensus_timestamp"),
                "seq": m.get("sequence_number"),
                "raw": m.get("message"),
                "decoded": decoded,
                "parsed": parsed
            })

        return messages

    except Exception as e:
        print("❌ Error fetching topic messages:", e)
        return []
