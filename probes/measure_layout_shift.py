"""量刷新时页面是否位移：刷新前后采样 main / chips 的 top。"""
import os, tempfile, time, json, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, ".onefeed", "tmp")
os.makedirs(TMP, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = TMP

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8791/"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(800)
    samples = []
    def probe(tag):
        box = page.evaluate("""() => {
          const main = document.querySelector('main');
          const chips = document.querySelector('main section');
          const first = document.querySelector('main .grid > *');
          return {
            mainTop: main ? Math.round(main.getBoundingClientRect().top) : null,
            sectionTop: chips ? Math.round(chips.getBoundingClientRect().top) : null,
            cardTop: first ? Math.round(first.getBoundingClientRect().top) : null,
            scrollY: Math.round(window.scrollY),
            progressWidth: (() => { const b = document.querySelector('header .bg-ink'); return b ? Math.round(b.getBoundingClientRect().width) : 0; })(),
          };
        }""")
        samples.append({"t": tag, **box})

    probe("before")
    page.click('header button[title="刷新六个平台"]')
    for i in range(20):
        page.wait_for_timeout(150)
        probe(f"+{(i+1)*150}ms")
    page.screenshot(path=os.path.join(ROOT, "design", "layout-shift-refresh.png"))
    browser.close()

main_tops = {s["mainTop"] for s in samples}
card_tops = {s["cardTop"] for s in samples}
print(json.dumps({
    "samples": len(samples),
    "mainTop_values": sorted(main_tops),
    "cardTop_values": sorted(card_tops),
    "max_main_shift": (max(main_tops) - min(main_tops)) if None not in main_tops else None,
    "max_card_shift": (max(card_tops) - min(card_tops)) if None not in card_tops else None,
    "first": samples[0],
    "peak": samples[2],
    "last": samples[-1],
}, ensure_ascii=False, indent=1))
