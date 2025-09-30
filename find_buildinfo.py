import json, glob, os

hits = []
for p in glob.glob(os.path.join("artifacts","build-info","*.json")):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        has_in  = "contracts/CoopTrust.sol" in d.get("input",{}).get("sources",{})
        has_out = d.get("output",{}).get("contracts",{}).get("contracts/CoopTrust.sol",{}).get("CoopTrust")
        if has_in and has_out:
            print("OK:", p)
            hits.append(p)
    except Exception as e:
        print("ERR:", p, e)

if not hits:
    print("No matching build-info found for CoopTrust.")
