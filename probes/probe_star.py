"""单点复测：星标与 Esc 回全部各自连做 5 次，看是抖动还是真问题。"""
from __future__ import annotations

import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
SOURCE = (ROOT / "probes" / "ops_frames.py").read_text(encoding="utf-8")
INIT = SOURCE.split('INIT = r"""')[1].split('"""')[0]

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1600)

    def measure(name, fn, window_ms=800):
        page.evaluate(INIT)
        page.wait_for_timeout(80)
        page.evaluate("window.__probe.start()")
        fn()
        page.wait_for_timeout(window_ms)
        st = page.evaluate("window.__probe.stop()")
        print(f"{name:16s} max={st['max']} jank={st['jank33']} long={st['longMs']}/{st['longMax']} first={st['firstMutMs']}", flush=True)

    for i in range(5):
        page.evaluate("window.scrollTo({top:0,behavior:'auto'})")
        page.wait_for_timeout(300)
        btn = page.locator('button[aria-label="稍后再看"], button[aria-label="移出稍后再看"]').first
        measure(f"star#{i}", lambda: btn.click())
    page.wait_for_timeout(800)

    for i in range(5):
        page.evaluate("window.scrollTo({top:0,behavior:'auto'})")
        page.wait_for_timeout(200)
        page.locator('button:has-text("B 站")').first.click()
        page.wait_for_timeout(900)
        measure(f"esc#{i}", lambda: page.keyboard.press("Escape"), 1000)
        page.wait_for_timeout(900)

    browser.close()
