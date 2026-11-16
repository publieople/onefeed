
import sys
from pathlib import Path
sys.path.insert(0, r"E:/Documents/deepseek-harness/default-workspace/onefeed")
from plugin_runtime.paths import ensure_temp_env
from plugin_runtime.capabilities import UA, _find_chrome
from playwright.sync_api import sync_playwright
ensure_temp_env()
msgs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=_find_chrome(), headless=True,
                           args=["--disable-blink-features=AutomationControlled"])
    pg = b.new_page(viewport={"width":1500,"height":520}, user_agent=UA, locale="zh-CN")
    pg.on("console", lambda m: msgs.append(f"{m.type}: {m.text[:160]}"))
    pg.on("requestfailed", lambda r: msgs.append(f"FAILED {r.url[:110]} {r.failure}"))
    pg.goto("http://127.0.0.1:8793/embed_probe2.html", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(7000)
    for f in pg.frames:
        if "douyin" in (f.url or ""):
            try:
                print("frame", f.url[:70], "| title:", f.title()[:40], "| body:", (f.inner_text("body") or "")[:90].replace("\n"," "))
            except Exception as e:
                print("frame", f.url[:70], "err", str(e)[:60])
    pg.screenshot(path="design/embed-douyin-official-player.png")
    b.close()
print("console/network issues:")
for m in msgs[:25]: print("  ", m)
