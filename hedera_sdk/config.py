# hedera_sdk/config.py
from dotenv import load_dotenv
load_dotenv()

import os
import logging
from dataclasses import dataclass
from datetime import datetime
from hedera import Client, AccountId, PrivateKey, PublicKey

# configure logging (so prints become manageable)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hedera.config")

@dataclass
class HederaConfig:
    network: str = os.getenv("HEDERA_NETWORK", "testnet")
    operator_id: str | None = os.getenv("HEDERA_OPERATOR_ID")
    operator_key: str | None = os.getenv("HEDERA_OPERATOR_KEY")
    operator_pub: str | None = os.getenv("HEDERA_PUBLIC_KEY")
    mirror_node_url: str = os.getenv("HEDERA_MIRROR_URL", "https://testnet.mirrornode.hedera.com")
    kyc_nft_id: str | None = os.getenv("KYC_NFT_ID")
    # EVM helper keys (optional)
    evm_private_key: str | None = os.getenv("HEDERA_EVM_PRIVATE_KEY")
    evm_account: str | None = os.getenv("HEDERA_EVM_ACCOUNT")

_cfg = HederaConfig()

# Global Hedera Client (initialized if operator creds present)
client = None
if _cfg.operator_id and _cfg.operator_key:
    try:
        priv_key = PrivateKey.fromString(_cfg.operator_key)
        pub_key = None
        if _cfg.operator_pub:
            try:
                pub_key = PublicKey.fromString(_cfg.operator_pub)
            except Exception as e:
                log.warning("Public key load failed (%s) — continuing with private key only", e)

        # Client.forName is used in your code; map testnet/mainnet
        if _cfg.network and _cfg.network.lower() in {"mainnet", "prod", "production"}:
            client = Client.forMainnet()
        else:
            client = Client.forTestnet()

        client.setOperator(AccountId.fromString(_cfg.operator_id), priv_key)

        # Try setting a request timeout if JVM jnius is available
        try:
            from jnius import autoclass
            Duration = autoclass('java.time.Duration')
            client.setRequestTimeout(Duration.ofSeconds(20))
        except Exception:
            # ignore if jnius not present
            pass

        log.info("✅ Hedera Client initialized for operator %s (network=%s)", _cfg.operator_id, _cfg.network)
    except Exception as e:
        client = None
        log.exception("❌ Hedera Client init failed: %s", e)
else:
    # don't loudly print — log at debug so you can enable it when needed
    log.debug("Hedera operator not configured: HEDERA_OPERATOR_ID / HEDERA_OPERATOR_KEY missing")

def get_config() -> HederaConfig:
    return _cfg

def record_file_on_hedera(filename: str, content: str) -> dict:
    safe = filename.replace("/", "_")
    out = os.path.join(os.getcwd(), f"_hedera_fs_{safe}")
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.utcnow().isoformat()}Z ---\n{content}\n")
    return {"file_id": f"local://{safe}"}
