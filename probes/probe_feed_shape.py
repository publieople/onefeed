
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.type + ": " + m.text) if m.type in ("error", "warning") else None)
    seen = {}
    def on_resp(r):
        if "/api/feed" in r.url:
            try:
                seen[r.url.split("/api/")[1][:60]] = list(r.json().keys())
            except Exception as e:
                seen[r.url] = "ERR " + str(e)
    page.on("response", on_resp)
    page.route("**/api/feed*", lambda route: route.continue_())
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_timeout(4000)
    print("keys:", json.dumps(seen, ensure_ascii=False)[:600])
    print("cards:", page.evaluate("document.querySelectorAll('[data-vt-item]').length"))
    print("errors:", errs[:5])
    b.close()
