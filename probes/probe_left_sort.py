"""复测：左栏收放 3 轮 + 排序来回 4 次。"""
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
    page.wait_for_timeout(1800)

    def measure(name, fn, window_ms=900):
        page.evaluate(INIT)
        page.wait_for_timeout(80)
        page.evaluate("window.__probe.start()")
        fn()
        page.wait_for_timeout(window_ms)
        st = page.evaluate("window.__probe.stop()")
        print(f"{name:18s} max={st['max']} jank={st['jank33']} long={st['longMs']}/{st['longMax']} first={st['firstMutMs']}", flush=True)
        return st

    def left_btn(*words):
        for w in words:
            loc = page.locator(f'button[title*="{w}"], button[aria-label*="{w}"]')
            if loc.count():
                return loc.first
        raise RuntimeError("no left button")

    for i in range(3):
        measure(f"collapse#{i}", lambda: left_btn("收起", "折叠").click())
        page.wait_for_timeout(700)
        measure(f"expand#{i}", lambda: left_btn("展开").click())
        page.wait_for_timeout(700)

    for i in range(4):
        word = "按热度" if i % 2 == 0 else "按新鲜度"
        measure(f"sort#{i}-{word}", lambda w=word: page.locator(f'button[aria-pressed]:has-text("{w}")').first.click(), 1100)
        page.wait_for_timeout(900)

    browser.close()
