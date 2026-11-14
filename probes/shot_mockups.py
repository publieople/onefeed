import os, sys, time
from pathlib import Path

TMP = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

HTML = (Path(__file__).resolve().parents[1] / "design" / "mockups.html").as_uri()
OUT = Path(__file__).resolve().parents[1] / "design"
shots = [("a", 0, "mock-a.png"), ("a", 1, "mock-a-drawer.png"), ("b", 0, "mock-b.png"), ("c", 0, "mock-c.png")]

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for theme, drawer, name in shots:
        page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        page.goto(HTML + "?theme=" + theme + "&drawer=" + str(drawer))
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / name))
        print("shot", name, page.viewport_size)
        page.close()
    b.close()
