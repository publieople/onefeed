import json, os, subprocess, sys
from pathlib import Path
BV = "BV1ZMWd6mE77"
bili = r"C:\Users\Publieople\.local\bin\bili.exe"
def run(env=None):
    e = os.environ.copy()
    for k in ("NO_PROXY", "no_proxy"): e.pop(k, None)
    if env: e.update(env)
    p = subprocess.run([bili, "video", "watch", BV, "--frames", "0", "--comments", "0"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, timeout=120)
    try:
        d = json.loads((p.stdout or "").strip()); brief = d.get("error") or {"ok": d.get("data", {}).get("bvid")}
    except Exception:
        brief = (p.stdout or "")[:100]
    print(f"parent={sys.executable} rc={p.returncode} {brief}")
run()
