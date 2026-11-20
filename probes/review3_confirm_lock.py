from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
out = {}
with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
              "--disable-backgrounding-occluded-windows"])
    page = br.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE + "/settings", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    # 「AI 助手」默认展开，别去点它（点一下反而收起来）
    page.evaluate("() => window.scrollTo(0, 900)")
    page.wait_for_timeout(500)
    out["scroll_before"] = page.evaluate("() => Math.round(window.scrollY)")
    btn = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>/清除所有 key/.test(x.textContent||'')); if(!b) return null; b.scrollIntoView({block:'center'}); const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
    out["clear_btn"] = btn
    if btn:
        page.mouse.click(btn["x"], btn["y"])
        page.wait_for_timeout(700)
        out["dialog"] = page.evaluate("() => document.querySelectorAll('[role=dialog]').length")
        y0 = page.evaluate("() => Math.round(window.scrollY)")
        page.mouse.move(700, 500)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(900)
        out["confirm_lock"] = {"y_before": y0, "y_after": page.evaluate("() => Math.round(window.scrollY)"),
                               "overflow": page.evaluate("() => getComputedStyle(document.documentElement).overflow")}
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        out["after_close"] = {"dialog": page.evaluate("() => document.querySelectorAll('[role=dialog]').length"),
                              "y": page.evaluate("() => Math.round(window.scrollY)")}
        # 关闭后滚轮应恢复
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(800)
        out["after_close_wheel_y"] = page.evaluate("() => Math.round(window.scrollY)")
    page.close()
    br.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
