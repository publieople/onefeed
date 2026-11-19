import json
from pathlib import Path
ROOT = Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")
conf = json.loads((ROOT / ".onefeed" / "settings.json").read_text("utf-8"))
print("top keys:", sorted(conf.keys()))
for i, p in enumerate(conf.get("ai_providers") or []):
    masked = {k: ("<set len=%d>" % len(str(v)) if k == "api_key" and v else v) for k, v in p.items()}
    print(i, json.dumps(masked, ensure_ascii=False))
print("ai_api_key:", "<set>" if conf.get("ai_api_key") else "<empty>")
print("ai_model:", conf.get("ai_model"), "| ai_base_url:", conf.get("ai_base_url"))
