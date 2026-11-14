import sys, json, hashlib
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from onefeed.market import dir_hash

root = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed-plugins\plugins\zhihu-hot")
print("files", [p.name for p in sorted(root.rglob("*")) if p.is_file()])
print("ours", dir_hash(root))

# 复刻 build_registry.py 的算法读一遍
import importlib.util
spec = importlib.util.spec_from_file_location("br", r"E:\Documents\deepseek-harness\default-workspace\onefeed-plugins\scripts\build_registry.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["br"] = mod
spec.loader.exec_module(mod)
print([n for n in dir(mod) if "hash" in n.lower() or "sha" in n.lower()])
