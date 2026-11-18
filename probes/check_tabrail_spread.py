"""单击换平台时胶囊要「从点的 chip 扩散出来」：新胶囊从窄条铺开、旧胶囊原地淡出、外圈淡影散开，
并且连点之后不留幽灵胶囊或残余淡影。"""
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


def check_spread(label, frames, target, wants):
    """wants = {x, w}: 目标胶囊的几何。返回问题列表。"""
    widths = [m["w"] for f in frames for m in f["masks"]]
    final = frames[-1]["masks"]
    bad = []
    if not widths:
        return [(label, "no-mask")]
    # 1) 新胶囊必须从窄条长到目标宽度（面积上的「扩散」而不是平移）
    if not any(w < wants["w"] * 0.75 for w in widths):
        bad.append((label, "no-narrow-start", widths[:6]))
    if not any(wants["w"] * 0.5 < w < wants["w"] - 3 for w in widths):
        bad.append((label, "no-mid-width", widths[:12]))
    # 2) 结束时只剩一条，且正好盖住目标 chip
    if len(final) != 1:
        bad.append((label, "final-mask-count", len(final)))
    elif abs(final[0]["x"] - wants["x"]) > 1.5 or abs(final[0]["w"] - wants["w"]) > 1.5:
        bad.append((label, "final-geometry", final[0], wants))
    # 3) 旧胶囊淡出而不是硬切：出现过 2 条 / 一条在淡出
    if not any(len(f["masks"]) >= 2 or any(m["o"] < 0.98 for m in f["masks"]) for f in frames):
        bad.append((label, "old-mask-hard-cut", [len(f["masks"]) for f in frames[:8]]))
    # 4) 外圈淡影：出现过、宽度等于 chip、透明度在降，最后清空
    blooms = [b for f in frames for b in f["blooms"]]
    if not blooms:
        bad.append((label, "no-bloom"))
    else:
        if abs(blooms[0]["w"] - wants["w"]) > 2:
            bad.append((label, "bloom-width", blooms[0]["w"], wants["w"]))
        if not any(b["o"] < blooms[0]["o"] for b in blooms[1:]):
            bad.append((label, "bloom-static", [b["o"] for b in blooms[:6]]))
    if frames[-1]["blooms"]:
        bad.append((label, "bloom-leftover", frames[-1]["blooms"]))
    print(
        label,
        "| 宽度", widths[:1], "→", widths[-1:],
        "| 中间宽度帧", sum(1 for w in widths if wants["w"] * 0.5 < w < wants["w"] - 3),
        "| 淡影", len(blooms), "| 结束遮罩", len(final),
    )
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

    cases = [("全部 → 抖音", "douyin"), ("抖音 → 知乎", "zhihu"), ("知乎 → 全部", "all")]
    for index, (label, target) in enumerate(cases):
        page.evaluate(SAMPLE_JS)
        page.locator('button[data-value="' + target + '"]').click()
        frames = sample(page)
        bad = check_spread(label, frames, target, boxes[target])
        if bad:
            problems.extend(bad)
        if index == 0:
            page.screenshot(path=str(SHOTS / "tabrail-spread-after.png"))
        page.wait_for_timeout(120)

    # 连点：四连击之后只能剩一条胶囊，不能留淡影
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
    page.screenshot(path=str(SHOTS / "tabrail-spread-rapid.png"))

    if errors:
        problems.append(("console", errors))
    ctx.close()
    browser.close()

print("errors:", errors if errors else "none")
if problems:
    print("FAIL", json.dumps(problems, ensure_ascii=False, default=str)[:1600])
    sys.exit(1)
print("OK")
