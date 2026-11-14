
import os, sys, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WS = r"E:\Documents\deepseek-harness\default-workspace"
TMP = os.path.join(WS, "onefeed", ".onefeed", "tmp"); os.makedirs(TMP, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = TMP
from playwright.sync_api import sync_playwright

bodies = []
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    ctx = b.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    def on_resp(resp):
        if "homefeed" in resp.url or "/feed/" in resp.url:
            try:
                j = resp.json()
            except Exception:
                return
            bodies.append({"url": resp.url, "json": j})
    page.on("response", on_resp)
    page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    page.mouse.wheel(0, 2400)
    page.wait_for_timeout(4000)
    print("captured", len(bodies))
    for bd in bodies[:2]:
        print("URL", bd["url"][:120])
        j = bd["json"]
        if isinstance(j, dict):
            print(" keys", list(j.keys())[:8])
            data = j.get("data") or {}
            print(" dataKeys", list(data.keys())[:10] if isinstance(data, dict) else type(data))
            items = data.get("items") if isinstance(data, dict) else None
            if items:
                print(" nItems", len(items))
                it = items[0]
                print(" itemKeys", list(it.keys())[:20])
                nc = it.get("note_card") or {}
                print(" noteKeys", list(nc.keys())[:20])
                print(" title", (nc.get("display_title") or "")[:60])
                print(" user", (nc.get("user") or {}).get("nickname"))
