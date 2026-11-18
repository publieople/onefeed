"""胶囊选中动效按状态分流：单选取平移、多选相邻从相邻段长、多选不相邻从点击中心扩散。

三条断言各自独立：
1. 全部 → 抖音（单选）：遮罩从「全部」连续滑到「抖音」，全程一条，无淡影；
2. 抖音 → Ctrl 加掘金（相邻）：从抖音那段长出来，中途宽度介于两者之间，无淡影；
3. 抖音+掘金 → Ctrl 加知乎（不相邻）：新胶囊从知乎 chip 中心长出来（起点窄且居中），有淡影；
最后连点确认不留幽灵胶囊与残余淡影。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = ROOT / "design"
URL = "http://127.0.0.1:8791/"

CHIPS = """() => {
  const rail = document.querySelector('[role=group]');
  const base = rail.getBoundingClientRect();
  const out = {};
  rail.querySelectorAll('button[data-value]').forEach((b) => {
    const r = b.getBoundingClientRect();
    out[b.dataset.value] = {x: Math.round((r.left - base.left) * 100) / 100, w: Math.round(r.width * 100) / 100};
  });
  return out;
}"""

SAMPLE_JS = """() => {
  // 采样在页面里跑：python 侧一次 evaluate 往返几十毫秒，弹簧动画早跑完了
  window.__frames = [];
  const rail = document.querySelector('[role=group]');
  const base = rail.getBoundingClientRect();
  const t0 = performance.now();
  const tick = () => {
    const masks = [];
    for (const node of rail.querySelectorAll(':scope > div[aria-hidden]')) {
      const box = node.getBoundingClientRect();
      const bg = getComputedStyle(node).backgroundColor;
      if (bg === 'rgba(0, 0, 0, 0)') continue;
      masks.push({
        x: Math.round((box.left - base.left) * 100) / 100,
        w: Math.round(box.width * 100) / 100,
        o: Math.round(parseFloat(getComputedStyle(node).opacity) * 100) / 100,
      });
    }
    const blooms = [];
    for (const node of rail.querySelectorAll(':scope > span[aria-hidden]')) {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      if (style.backgroundColor === 'rgba(0, 0, 0, 0)') continue;
      blooms.push({
        x: Math.round((box.left - base.left) * 100) / 100,
        w: Math.round(box.width * 100) / 100,
        o: Math.round(parseFloat(style.opacity) * 100) / 100,
      });
    }
    window.__frames.push({ t: Math.round(performance.now() - t0), masks, blooms });
    if (performance.now() - t0 < 900) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}"""


def sample(page, ms=900):
    page.wait_for_timeout(ms)
    return page.evaluate("() => window.__frames")


def geom_ok(mask, want, tol=1.5):
    return abs(mask["x"] - want["x"]) <= tol and abs(mask["w"] - want["w"]) <= tol


def check_slide(label, frames, start, end):
    bad = []
    singles = [f["masks"][0] for f in frames if len(f["masks"]) == 1]
    if not singles:
        return [(label, "no-mask")]
    lo, hi = sorted([start["x"], end["x"]])
    between = [
        m for m in singles
        if lo + 6 < m["x"] < hi - 6 and (hi - lo - abs(end["w"] - start["w"])) > 12
    ]
    if not between:
        bad.append((label, "no-intermediate-x", sorted({m["x"] for m in singles})[:12]))
    if not geom_ok(singles[-1], end):
        bad.append((label, "final-geometry", singles[-1], end))
    if any(f["blooms"] for f in frames):
        bad.append((label, "unexpected-bloom", [f["blooms"] for f in frames if f["blooms"]][:2]))
    print(label, "| 平移 x", singles[0]["x"], "→", singles[-1]["x"], "| 中间帧", len(between))
    return bad


def check_adjacent(label, frames, base_chip, want):
    bad = []
    masks = [m for f in frames for m in f["masks"]]
    final = frames[-1]["masks"]
    if not masks:
        return [(label, "no-mask")]
    narrow = min(m["w"] for m in masks)
    if narrow > base_chip["w"] + 6:
        bad.append((label, "no-adjacent-start", narrow, base_chip["w"]))
    if not any(base_chip["w"] + 4 < m["w"] < want["w"] - 3 for m in masks):
        bad.append((label, "no-mid-width", sorted({m["w"] for m in masks})[:12]))
    if len(final) != 1 or not geom_ok(final[0], want):
        bad.append((label, "final-geometry", final, want))
    if any(f["blooms"] for f in frames):
        bad.append((label, "unexpected-bloom", [f["blooms"] for f in frames if f["blooms"]][:2]))
    print(label, "| 宽度", sorted({m["w"] for m in masks})[:4], "→", want["w"])
    return bad


def check_center(label, frames, chip):
    bad = []
    two = [f["masks"] for f in frames if len(f["masks"]) == 2]
    if not two:
        return [(label, "no-two-masks", [len(f["masks"]) for f in frames][:8])]
    small = [m for f in two for m in f if m["w"] < chip["w"] * 0.7]
    if not small:
        bad.append((label, "no-narrow-birth", sorted({round(m["w"], 1) for f in two for m in f["masks"]})[:8]))
    else:
        mask = small[0]
        center = mask["x"] + mask["w"] / 2
        want = chip["x"] + chip["w"] / 2
        if abs(center - want) > 4:
            bad.append((label, "birth-not-centered", round(center, 1), round(want, 1)))
    final = [m for m in frames[-1]["masks"]]
    if len(final) != 2:
        bad.append((label, "final-mask-count", final))
    blooms = [b for f in frames for b in f["blooms"]]
    if not blooms:
        bad.append((label, "no-bloom"))
    else:
        if abs(blooms[0]["w"] - chip["w"]) > 2:
            bad.append((label, "bloom-width", blooms[0]["w"], chip["w"]))
        if not any(b["o"] < blooms[0]["o"] for b in blooms[1:]):
            bad.append((label, "bloom-static", [b["o"] for b in blooms[:6]]))
    if frames[-1]["blooms"]:
        bad.append((label, "bloom-leftover", frames[-1]["blooms"]))
    print(label, "| 起点宽", [round(m["w"], 1) for m in small][:3], "| 淡影", len(blooms))
    return bad


problems = []
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("button[data-value]")
    page.wait_for_timeout(700)
    boxes = page.evaluate(CHIPS)

    # 1) 单选：全部 → 抖音，应该平移
    page.evaluate(SAMPLE_JS)
    page.locator('button[data-value="douyin"]').click()
    problems.extend(check_slide("全部 → 抖音（平移）", sample(page), boxes["all"], boxes["douyin"]))
    page.screenshot(path=str(SHOTS / "tabrail-mode-slide.png"))
    page.wait_for_timeout(200)

    # 2) 多选相邻：Ctrl 加掘金，应该从抖音那段长过去
    page.evaluate(SAMPLE_JS)
    page.locator('button[data-value="juejin"]').click(modifiers=["Control"])
    run_end = {
        "x": boxes["douyin"]["x"],
        "w": round(boxes["juejin"]["x"] + boxes["juejin"]["w"] - boxes["douyin"]["x"], 2),
    }
    problems.extend(check_adjacent("抖音 + 掘金（相邻扩散）", sample(page), boxes["douyin"], run_end))
    page.screenshot(path=str(SHOTS / "tabrail-mode-adjacent.png"))
    page.wait_for_timeout(200)

    # 3) 多选不相邻：Ctrl 加知乎，应该从知乎 chip 中心扩散
    page.evaluate(SAMPLE_JS)
    page.locator('button[data-value="zhihu"]').click(modifiers=["Control"])
    problems.extend(check_center("+ 知乎（中心扩散）", sample(page), boxes["zhihu"]))
    page.screenshot(path=str(SHOTS / "tabrail-mode-center.png"))
    page.wait_for_timeout(200)

    # 4) 连点：单选之间来回跳，最后只能剩一条胶囊、不能留淡影
    for target in ["bilibili", "xiaohongshu", "douyin", "juejin"]:
        page.locator('button[data-value="' + target + '"]').click()
        page.wait_for_timeout(90)
    page.wait_for_timeout(1400)
    residue = page.evaluate(
        """() => {
          const rail = document.querySelector('[role=group]');
          const masks = rail.querySelectorAll(':scope > div[aria-hidden]').length;
          // 焦点环也是 span[aria-hidden]，但它背景透明，不能算进淡影
          const blooms = Array.from(rail.querySelectorAll(':scope > span[aria-hidden]')).filter(
            (node) => getComputedStyle(node).backgroundColor !== 'rgba(0, 0, 0, 0)',
          ).length;
          return {masks, blooms};
        }"""
    )
    print("连点四次后残留:", residue)
    if residue["masks"] != 1 or residue["blooms"] != 0:
        problems.append(("rapid", residue))
    page.screenshot(path=str(SHOTS / "tabrail-mode-rapid.png"))

    if errors:
        problems.append(("console", errors))
    ctx.close()
    browser.close()

print("errors:", errors if errors else "none")
if problems:
    print("FAIL", json.dumps(problems, ensure_ascii=False, default=str)[:1800])
    sys.exit(1)
print("OK")