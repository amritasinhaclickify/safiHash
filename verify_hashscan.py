import json, os, urllib.request

ADDR  = "0xa49fD8C85D12117C38d70e27356D9acD3E4E8DFd"
CHAIN = "296"
BF    = r"artifacts/build-info/REPLACE_ME.json"   # <-- Step 1 se jo OK file mili, yahan daalo

with open(BF, "r", encoding="utf-8") as f:
    data = json.load(f)

solc_input = data["input"]
ver = data.get("solcLongVersion") or data.get("solcVersion") or "0.8.30+commit.73712a01"

payload = {
  "address": ADDR,
  "chain": CHAIN,
  "files": { "value": { "SolcJsonInput.json": json.dumps(solc_input, separators=(',',':')) } },
  "compilerVersion": ver
}

req = urllib.request.Request(
    "https://server-verify.hashscan.io/verify/solc-json",
    data=json.dumps(payload).encode(),
    headers={"Content-Type":"application/json"},
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as e:
    print("HTTPError:", e.code, e.read().decode())
