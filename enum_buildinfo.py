import json, glob, os

any_hit = False
for bf in glob.glob(os.path.join("artifacts","build-info","*.json")):
    try:
        with open(bf, encoding="utf-8") as f:
            d = json.load(f)
        contracts = d.get("output",{}).get("contracts",{}) or {}
        ver = d.get("solcLongVersion") or d.get("solcVersion")
        print("\n=== BUILD-INFO:", bf, "===")
        print("solc:", ver)
        found_here = False
        for src_path, names in contracts.items():
            # names is dict of contractName -> {abi, evm, ...}
            for name, meta in names.items():
                bytecode = (meta.get("evm",{}).get("bytecode",{}).get("object") or "")
                is_empty = (bytecode.strip().lower() in ("","0x"))
                print(f" - {name}  @ {src_path}  bytecode_empty={is_empty}")
                if name.lower()=="cooptrust" or src_path.replace("\\","/").endswith("CoopTrust.sol"):
                    found_here = True
                    any_hit = True
        if found_here:
            print(">>> This build-info contains CoopTrust ")
    except Exception as e:
        print("ERR:", bf, e)

if not any_hit:
    print("\nNo CoopTrust found in any build-info. Re-compile the project (npx hardhat compile) and try again.")
