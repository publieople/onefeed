import json, os, subprocess, time
bili = r"C:\Users\Publieople\.local\bin\bili.exe"
home = r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\toolhome\bili-cli"
env = {k: v for k, v in os.environ.items() if k != "NO_PROXY" and k != "no_proxy"}
env["BILI_CLI_HOME"] = home
t = time.time()
p = subprocess.run([bili, "video", "watch", "BV1ZMWd6mE77", "--frames", "0", "--comments", "3", "--max-chars", "6000"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=180)
ms = int((time.time() - t) * 1000)
out = (p.stdout or "").strip()
try:
    d = json.loads(out); data = d.get("data") or {}
    tr = data.get("transcript") or {}
    print("rc", p.returncode, "ms", ms)
    print("title:", data.get("title"))
    print("ai_summary:", (data.get("ai_summary") or "")[:80])
    print("transcript source:", tr.get("source"), "chars:", len(tr.get("text") or ""))
    print("chapters:", len(data.get("chapters") or []), "comments:", len(data.get("hot_comments") or []))
except Exception:
    print("rc", p.returncode, "ms", ms, "out:", out[:400])
print("stderr:", (p.stderr or "")[:300])
