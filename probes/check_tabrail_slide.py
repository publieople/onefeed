"""单击切换时胶囊必须滑过去：采样遮罩 x，断言存在中间帧。"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = ROOT / "design"
URL = "http://127.0.0.1:8791/"

RECTS = """() => {
  const rail = document.querySelector('[role=group]');
  const base = rail.getBoundingClientRect();
  return Array.from(rail.querySelectorAll(':scope > div[aria-hidden]')).map((node) => {
    const box = node.getBoundingClientRect();
    return {x: Math.round((box.left - base.left) * 100) / 100, w: Math.round(box.width * 100) / 100};
  });
}"""


def chips(page):
    return page.evaluate("""() => {
      const rail = document.querySelector('[role=group]');
      const base = rail.getBoundingClientRect();
      const out = {};
      rail.querySelectorAll('button[data-value]').forEach((b) => {
        const r = b.getBoundingClientRect();
        out[b.dataset.value] = {x: Math.round((r.left - base.left) * 100) / 100, w: Math.round(r.width * 100) / 100};
      });
      return out;
    }""")


def sample(page, out, ms=520, step=16):
    end = time.time() + ms / 1000
    while time.time() < end:
        out.append({"t": round((time.time() - start) * 1000), "masks": page.evaluate(RECTS)})
        page.wait_for_timeout(step)


def check_slide(label, path, out):
    xs = [f["masks"][0]["x"] for f in out if f["masks"]]
    ws = [f["masks"][0]["w"] for f in out if f["masks"]]
    counts = {len(f["masks"]) for f in out}
    if not xs:
        print(label, "FAIL 没有遮罩")
        return [label, "no-mask"]
    first, last = xs[0], xs[-1]
    mids = [x for x in xs if min(first, last) + 1 < x < max(first, last) - 1]
    print(label, "x", first, "→", last, "| 中间帧", len(mids), sorted({round(x) for x in mids})[:8], "| w", ws[0], "→", ws[-1], "| 遮罩条数", counts)
    bad = []
    if abs(first - last) < 20:
        bad.append(("no-travel", first, last))
    if not mids:
        bad.append(("no-midframe", xs))
    if len(counts) != 1 or counts != {1}:
        bad.append(("mask-count", counts))
    return bad


global_start = time.time()
problems = []

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("button[data-value]")
    page.wait_for_timeout(700)

    frames = []
    start = time.time()
    page.locator('button[data-value="douyin"]').click()
    sample(page, frames)
    page.wait_for_timeout(200)
    bad = check_slide("全部 → 抖音", None, frames)
    if bad:
        problems.append(bad)
    page.screenshot(path=str(SHOTS / "tabrail-slide-after.png"))

    frames = []
    start = time.time()
    page.locator('button[data-value="zhihu"]').click()
    sample(page, frames)
    page.wait_for_timeout(200)
    bad = check_slide("抖音 → 知乎", None, frames)
    if bad:
        problems.append(bad)

    frames = []
    start = time.time()
    page.locator('button[data-value="all"]').click()
    sample(page, frames)
    page.wait_for_timeout(200)
    bad = check_slide("知乎 → 全部", None, frames)
    if bad:
        problems.append(bad)
    page.screenshot(path=str(SHOTS / "tabrail-slide-back.png"))

    if errors:
        problems.append(("console", errors))
    ctx.close()
    browser.close()

print("errors:", errors if errors else "none")
if problems:
    print("FAIL", json.dumps(problems, ensure_ascii=False, default=str)[:1200])
    sys.exit(1)
print("OK")
