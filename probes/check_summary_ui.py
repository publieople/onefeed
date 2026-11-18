"""探针：详情页 AI 总结 → 点时间戳 → 原文页签的播放器是否带 t= 秒。"""
import os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8791/item/bilibili%3Avideo%3ABV1ZMWd6mE77"
SHOT = ROOT / "design" / "summary-seek.png"

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=False)
    page = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_selector("button:has-text('3:00')", timeout=90000)
    print("summary ready")
    # 点 3:00 → 应切到「原文」并带 t=180
    page.click("button:has-text('3:00')")
    page.wait_for_selector("iframe", timeout=30000)
    time.sleep(6)
    src = page.eval_on_selector("iframe", "el => el.src")
    print("iframe src:", src)
    print("t=180 in src:", "t=180" in src, "| autoplay:", "autoplay=1" in src)
    pressed = page.eval_on_selector_all("button[aria-pressed]", "els => els.map(e => [e.textContent, e.getAttribute('aria-pressed')])")
    print("tabs:", pressed)
    page.screenshot(path=str(SHOT))
    print("shot:", SHOT, SHOT.stat().st_size)
    print("pageerror:", errors)
    b.close()
