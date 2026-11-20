"""C-02：确认框开着的时候，全局热键不能穿透。"""
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
    page.goto(BASE + "/market", wait_until="load")
    page.wait_for_timeout(1500)

    # 找一张卡上的「卸载」
    buttons = page.get_by_role("button", name="卸载")
    check("市场页有卸载按钮", buttons.count() > 0, buttons.count())
    buttons.first.click()
    page.wait_for_timeout(400)
    dialog = page.locator('[role="dialog"]')
    check("卸载弹出确认框", dialog.count() == 1, dialog.count())

    page.keyboard.press("?")
    page.wait_for_timeout(400)
    help_open = page.evaluate("() => document.body.innerText.includes('键盘快捷键')")
    check("确认框开着时 ? 不会叠出快捷键面板", not help_open)

    before = page.evaluate("() => document.querySelector('[data-shell-left]')?.getAttribute('data-shell-left')")
    page.keyboard.press("[")
    page.wait_for_timeout(500)
    after = page.evaluate("() => document.querySelector('[data-shell-left]')?.getAttribute('data-shell-left')")
    check("确认框开着时 [ 不会收左栏", before == after, f"{before}->{after}")

    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    check("Esc 关掉确认框", page.locator('[role="dialog"]').count() == 0)

    print("\n失败:", fails if fails else "无", flush=True)
    browser.close()
