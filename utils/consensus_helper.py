# utils/consensus_helper.py
import os, json, re

# Hedera SDK Java binding wrapper
try:
    from hedera_sdk.consensus_service import publish_to_consensus as sdk_publish
except ImportError:
    import uuid
    def sdk_publish(topic_id, message):
        print(f"[Mock Hedera Publish] topic:{topic_id} message:{message}")
        return {"status": "ok", "topic": topic_id, "message_id": str(uuid.uuid4())}

_TOPIC_ENV_KEYS = ("HEDERA_TOPIC_ID", "HEDERA_CONSENSUS_TOPIC_ID")
_TOPIC_FALLBACK = "0.0.6613182"
_TOPIC_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[a-z0-9]+)?$")

def _get_topic_id() -> str:
    for k in _TOPIC_ENV_KEYS:
        v = os.getenv(k)
        if v:
            return v.strip()
    return _TOPIC_FALLBACK

def publish_to_consensus(message):
    """
    Always read topic id from env; send JSON/string as the *message*.
    Also retries once with swapped args if SDK raises 'Invalid ID ...' by mistake.
    """
    topic_id = _get_topic_id()
    if not _TOPIC_RE.match(topic_id):
        print(f"[Consensus Helper] Bad topic id '{topic_id}', set HEDERA_TOPIC_ID like 0.0.12345")
        return {"status": "error", "error": f"Invalid topic id: {topic_id}"}

    # normalize payload to string
    message_str = json.dumps(message, default=str, ensure_ascii=False) if isinstance(message, dict) else str(message)

    try:
        return sdk_publish(topic_id, message_str)
    except Exception as e:
        # If someone flipped the SDK arg order, error often says 'Invalid ID "{...}"'
        s = str(e)
        if "Invalid ID" in s and (message_str.startswith("{") or message_str.startswith("[")):
            try:
                # retry with args swapped (defensive)
                return sdk_publish(message_str, topic_id)
            except Exception as e2:
                print(f"[Consensus Helper] Retry failed: {e2}")
                return {"status": "error", "error": str(e2)}
        print(f"[Consensus Helper] Failed to publish: {e}")
        return {"status": "error", "error": str(e)}
