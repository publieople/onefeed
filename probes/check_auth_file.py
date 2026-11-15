import json, sys, os
sys.stdout.reconfigure(encoding="utf-8")
from onefeed import auth
from plugin_runtime.paths import state_root

path = state_root() / "cookies" / "douyin.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({"plugin": "douyin", "cookies": [
    {"name": "ttwid", "value": "x", "domain": ".douyin.com", "path": "/"},
    {"name": "sessionid", "value": "y", "domain": ".douyin.com", "path": "/"}]}), encoding="utf-8")
print("file-only check:", json.dumps({k: v for k, v in auth.check("douyin").items() if k != "path"}, ensure_ascii=False))
path.unlink()
print("after delete:", json.dumps(auth.check("douyin"), ensure_ascii=False))
print("cli describe:", json.dumps(auth.describe("bilibili"), ensure_ascii=False))
