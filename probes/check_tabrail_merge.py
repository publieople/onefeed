"""胶囊合并：按住 Ctrl 往两个已选胶囊中间再塞一个时，中间那段不能闪白。

验的是三件事：
1. 合并过程中每个选中项的文字始终被不透明的深色胶囊盖着（不许出现「先变回未选中」的中间帧）；
2. 合并结束后只剩一条胶囊，宽度等于三个 chip 之和；
3. 连续快速切换三次之后，淡出用的幽灵胶囊全部清掉，不会永久留在 DOM 里。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

URL = "http://127.0.0.1:8791/"
SHOTS = ROOT / "design"
SHOTS.mkdir(exist_ok=True)

SAMPLE = """(ids) => {
  window.__cov = { frames: 0, bad: [], masks: [] };
  const rail = document.querySelector('[role=group]');
  if (!rail) return false;
  const t0 = performance.now();
  const tick = () => {
    const rects = {};
    for (const button of rail.querySelectorAll('button[data-value]')) {
      const span = button.querySelector('span[data-inner]');
      if (span) rects[button.dataset.value] = span.getBoundingClientRect();
    }
    const masks = [];
    for (const node of rail.querySelectorAll(':scope > div[aria-hidden]')) {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      if (style.backgroundColor === 'rgba(0, 0, 0, 0)') continue;
      masks.push({ x: box.left, y: box.top, r: box.right, b: box.bottom, o: Number(style.opacity) });
    }
    const c = window.__cov;
    c.frames += 1;
    const pressed = new Set(
      Array.from(rail.querySelectorAll('button[aria-pressed=true]')).map((b) => b.dataset.value)
    );
    for (const id of ids) {
      // 从点下去到这个 chip 真的变成选中之前，它本来就该是白底（React 还没提交）
      if (!pressed.has(id)) continue;
      const s = rects[id];
      if (!s) { c.bad.push({ t: Math.round(performance.now() - t0), id, why: 'no span' }); continue; }
      const ok = masks.some((m) => m.o > 0.6 && m.x <= s.left + 1.5 && m.r >= s.right - 1.5 && m.y <= s.top + 1.5 && m.b >= s.bottom - 1.5);
      if (!ok) c.bad.push({ t: Math.round(performance.now() - t0), id, masks: masks.length });
    }
    if (performance.now() - t0 < 760) requestAnimationFrame(tick);
    else c.masks = masks.map((m) => ({ w: Math.round(m.r - m.x), o: Math.round(m.o * 100) / 100 }));
  };
  requestAnimationFrame(tick);
  return true;
}"""

COUNT = """() => {
  const rail = document.querySelector('[role=group]');
  if (!rail) return { masks: -1 };
  const nodes = Array.from(rail.querySelectorAll(':scope > div[aria-hidden]'));
  return {
    masks: nodes.filter((n) => getComputedStyle(n).backgroundColor !== 'rgba(0, 0, 0, 0)').length,
    widths: nodes.map((n) => Math.round(n.getBoundingClientRect().width)),
    pressed: Array.from(rail.querySelectorAll('button[aria-pressed=true]')).map((b) => b.dataset.value),
  };
}"""

fails = []


def ok(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name.ljust(26) + (str(extra) if extra != "" else ""))
    if not cond:
        fails.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_selector("button[data-value=bilibili]", timeout=20000)

    def chip(name):
        return page.locator('button[data-value="%s"]' % name)

    # 先选两个不相邻的：B 站、抖音
    chip("bilibili").click()
    chip("douyin").click(modifiers=["Control"])
    page.wait_for_timeout(320)
    before = page.evaluate(COUNT)
    ok("先有两个独立胶囊", before["masks"] == 2, before["widths"])

    widths = page.evaluate(
        """() => Object.fromEntries(['bilibili','xiaohongshu','douyin'].map((id) => {
          const b = document.querySelector('button[data-value=' + id + ']');
          return [id, Math.round(b.getBoundingClientRect().width)];
        }))"""
    )
    expect = widths["bilibili"] + widths["xiaohongshu"] + widths["douyin"]

    # 中间那个补上：三个应该并成一条
    page.evaluate(SAMPLE, ["bilibili", "xiaohongshu", "douyin"])
    page.wait_for_timeout(40)
    chip("xiaohongshu").click(modifiers=["Control"])
    page.wait_for_timeout(950)
    cov = page.evaluate("() => window.__cov")
    after = page.evaluate(COUNT)
    ok("合并后并成一条", after["masks"] == 1, after["widths"])
    ok("宽度等于三个 chip 之和", abs(after["widths"][0] - expect) <= 10, (after["widths"], expect))
    ok("合并过程无露白帧", len(cov["bad"]) == 0, cov["bad"][:4])
    ok("采样够密", cov["frames"] >= 20, cov["frames"])

    # 截图：合并中与合并后
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_selector("button[data-value=bilibili]", timeout=20000)
    chip("bilibili").click()
    chip("douyin").click(modifiers=["Control"])
    page.wait_for_timeout(300)
    chip("xiaohongshu").click(modifiers=["Control"])
    page.wait_for_timeout(110)
    rail = page.locator('[role=group]')
    rail.screenshot(path=str(SHOTS / "tabrail-merge-mid.png"))
    page.wait_for_timeout(500)
    rail.screenshot(path=str(SHOTS / "tabrail-merge-done.png"))

    # 旧 bug：幽灵胶囊的定时器被下一次选择取消，就一直留在 DOM 里
    chip("all").click()
    chip("bilibili").click(modifiers=["Control"])
    page.wait_for_timeout(120)
    chip("all").click()
    page.wait_for_timeout(1000)
    settle = page.evaluate(COUNT)
    ok("连点三次不留幽灵胶囊", settle["masks"] == 1, settle)

    ok("没有页面报错", not errors, errors[:2])
    browser.close()

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
