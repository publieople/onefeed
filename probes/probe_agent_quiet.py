"""P-10：Agent 中段静默时界面要自己动（「还在翻，已 Ns」）。"""
from __future__ import annotations

import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1200)

    # 用 "/" 快捷键唤起输入框，避开中文字面量在控制台里的编码问题
    page.keyboard.press("/")
    page.wait_for_timeout(400)
    page.keyboard.insert_text("挑两条今天 B 站讲 AI 的视频，各写一句总结")
    page.keyboard.press("Enter")

    seen = []
    for _ in range(16):
        page.wait_for_timeout(1000)
        txt = page.evaluate("() => document.body.innerText")
        if "还在翻，已" in txt:
            seen.append("quiet-counter")
            break
        if "下一步…" in txt:
            seen.append("next-step")
    print("看到:", seen, flush=True)
    page.screenshot(path=str(TMP / "shot-agent-quiet.png"))
    browser.close()
