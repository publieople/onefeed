"""量胶囊文字在选中前后的位置：反色遮罩方案的核心验收。"""
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

URL = "http://127.0.0.1:8791/"
SHOTS = ROOT / "design"
SHOTS.mkdir(exist_ok=True)

MEASURE = """() => {
  const rail = document.querySelector('[role=group]');
  if (!rail) return null;
  const base = rail.getBoundingClientRect();
  const out = {};
  for (const button of rail.querySelectorAll('button[data-value]')) {
    const span = button.querySelector('span[data-inner]');
    if (!span) continue;
    const box = span.getBoundingClientRect();
    out[button.dataset.value] = {
      x: Math.round((box.left - base.left) * 100) / 100,
      w: Math.round(box.width * 100) / 100,
      color: getComputedStyle(span).color,
    };
  }
  return out;
}"""

MASKS = """() => {
  const rail = document.querySelector('[role=group]');
  if (!rail) return [];
  const live = {};
  for (const button of rail.querySelectorAll('button[data-value]')) {
    const span = button.querySelector('span[data-inner]');
    if (!span) continue;
    const box = span.getBoundingClientRect();
    live[button.dataset.value] = {
      x: Math.round(box.left * 100) / 100,
      y: Math.round(box.top * 100) / 100,
      w: Math.round(box.width * 100) / 100,
      h: Math.round(box.height * 100) / 100,
    };
  }
  return Array.from(rail.querySelectorAll(':scope > div[aria-hidden]')).map((node) => {
    const box = node.getBoundingClientRect();
    const copies = [];
    node.querySelectorAll('[data-inner]').forEach((span) => {
      const q = span.getBoundingClientRect();
      const label = span.textContent || '';
      const key = Object.keys(live).find((id) => label.startsWith(id === 'all' ? '全部' : id));
      copies.push({
        text: label,
        x: Math.round(q.left),
        y: Math.round(q.top),
        w: Math.round(q.width * 100) / 100,
        h: Math.round(q.height * 100) / 100,
        color: getComputedStyle(span).color,
        expect: live[span.closest('div').dataset.copyOf] || null,
      });
    });
    return {
      x: Math.round(box.left),
      w: Math.round(box.width),
      h: Math.round(box.height),
      radius: getComputedStyle(node).borderRadius,
      bg: getComputedStyle(node).backgroundColor,
      copies,
    };
  });
}"""


def copy_mismatch(masks):
    """副本必须单行、宽度等于原字、颜色是反色（白），否则文字会被折行或看不清。"""
    bad = []
    for mask in masks:
        for copy in mask.get("copies", []):
            expect = copy.get("expect")
            if not expect:
                bad.append((copy["text"], "no-live-box"))
                continue
            if abs(copy["x"] - expect["x"]) > 1.5:
                bad.append((copy["text"], "x", copy["x"], expect["x"]))
            if abs(copy["w"] - expect["w"]) > 1.5:
                bad.append((copy["text"], "width", copy["w"], expect["w"]))
            if copy["h"] > expect["h"] + 2:
                bad.append((copy["text"], "wrapped", copy["h"], expect["h"]))
            if copy["color"] != "rgb(255, 255, 255)":
                bad.append((copy["text"], "color", copy["color"]))
    return bad


def diff(before, after):
    bad = []
    for key, old in before.items():
        new = after.get(key)
        if new is None:
            bad.append((key, "missing"))
            continue
        if abs(new["x"] - old["x"]) > 0.5 or abs(new["w"] - old["w"]) > 0.5:
            bad.append((key, old, new))
    return bad


def main():
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("button[data-value]", timeout=15000)
        time.sleep(0.6)

        base = page.evaluate(MEASURE)
        if not base:
            print("no rail")
            return 1
        print("chips:", len(base))

        # 单选：抖音
        page.locator('button[data-value="douyin"]').click()
        page.wait_for_timeout(60)
        during = page.evaluate(MEASURE)
        page.wait_for_timeout(420)
        after = page.evaluate(MEASURE)
        for stage, snap in (("during", during), ("after", after)):
            bad = diff(base, snap)
            print(stage, "text drift:", bad if bad else "none")
            if bad:
                problems.append((stage, bad))
        masks = page.evaluate(MASKS)
        print("masks:", json.dumps(masks, ensure_ascii=False))
        if len(masks) != 1:
            problems.append(("mask-count", masks))
        bad = copy_mismatch(masks)
        print("copy mismatch:", bad if bad else "none")
        if bad:
            problems.append(("copy", bad))
        page.screenshot(path=str(SHOTS / "tabrail-mask-single.png"))

        # Ctrl 加相邻的掘金：应合成一条
        page.locator('button[data-value="juejin"]').click(modifiers=["Control"])
        page.wait_for_timeout(60)
        during2 = page.evaluate(MEASURE)
        page.wait_for_timeout(420)
        after2 = page.evaluate(MEASURE)
        for stage, snap in (("multi-during", during2), ("multi-after", after2)):
            bad = diff(base, snap)
            print(stage, "text drift:", bad if bad else "none")
            if bad:
                problems.append((stage, bad))
        masks2 = page.evaluate(MASKS)
        print("masks multi:", json.dumps(masks2, ensure_ascii=False))
        if len(masks2) != 1:
            problems.append(("mask-count-multi", masks2))
        else:
            douyin = page.locator('button[data-value="douyin"]')
            juejin = page.locator('button[data-value="juejin"]')
            a = douyin.bounding_box()
            b = juejin.bounding_box()
            expect = round(b["x"] + b["width"] - a["x"])
            print("merged width:", masks2[0]["w"], "expect", expect)
            if abs(masks2[0]["w"] - expect) > 8:
                problems.append(("merged-width", masks2[0]["w"], expect))
        page.screenshot(path=str(SHOTS / "tabrail-mask-merged.png"))

        # 断开：再 Ctrl 加知乎热榜（和掘金隔着 V2EX、知乎），应该变两条
        page.locator('button[data-value="zhihu-hot"]').click(modifiers=["Control"])
        page.wait_for_timeout(600)
        masks3 = page.evaluate(MASKS)
        print("masks split:", json.dumps(masks3, ensure_ascii=False))
        if len(masks3) != 2:
            problems.append(("mask-count-split", masks3))
        after3 = page.evaluate(MEASURE)
        bad = diff(base, after3)
        print("split text drift:", bad if bad else "none")
        if bad:
            problems.append(("split", bad))
        page.screenshot(path=str(SHOTS / "tabrail-mask-split.png"))

        if errors:
            problems.append(("console", errors))
        context.close()
        browser.close()

    print("errors:", errors if errors else "none")
    if problems:
        print("FAIL", json.dumps(problems, ensure_ascii=False, default=str)[:1500])
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
