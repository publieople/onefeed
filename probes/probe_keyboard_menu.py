"""C-01/I-01/I-02 真机断言：菜单键盘焦点、Esc 归位、星标撤销。"""
from __future__ import annotations

import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
fails = []

def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  " + str(detail)), flush=True)
    if not ok:
        fails.append(name)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1500)

    # C-01：键盘打开菜单，焦点要落在第一项
    trigger = page.locator('button[aria-label="更多操作"]').first
    trigger.focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(350)
    active = page.evaluate("() => ({role: document.activeElement?.getAttribute('role'), text: (document.activeElement?.textContent||'').trim().slice(0,20)})")
    check("menu 打开后焦点在菜单项", active["role"] == "menuitem", active)

    # ArrowDown 在菜单项之间移动
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(200)
    second = page.evaluate("() => (document.activeElement?.textContent||'').trim().slice(0,20)")
    check("ArrowDown 换到下一项", second != active["text"], second)

    page.keyboard.press("Escape")
    page.wait_for_timeout(350)
    back = page.evaluate("() => (document.activeElement?.getAttribute('aria-label')||'')")
    check("Esc 关菜单并把焦点还给触发按钮", back == "更多操作", back)

    # I-01：星标要有 toast + 撤销
    star = page.locator('button[aria-label="稍后再看"]').first
    before = page.locator('button[aria-label="移出稍后再看"]').count()
    star.click()
    page.wait_for_timeout(300)
    toast = page.locator('[data-toast], [role="status"]').first
    text = page.evaluate("() => document.body.innerText.includes('已加入稍后再看')")
    check("星标后出现「已加入稍后再看」提示", text)
    undo = page.get_by_role("button", name="撤销")
    check("提示里带撤销按钮", undo.count() > 0)
    after = page.locator('button[aria-label="移出稍后再看"]').count()
    check("星标状态已变成已保存", after > before, f"{before}->{after}")
    if undo.count():
        undo.first.click()
        page.wait_for_timeout(600)
        reverted = page.locator('button[aria-label="移出稍后再看"]').count()
        check("点撤销后回到未保存", reverted < after, f"{after}->{reverted}")

    print("\n失败:", fails if fails else "无", flush=True)
    browser.close()
