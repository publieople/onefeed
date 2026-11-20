
"""交互帧与时序实测（第三版：CDP 直发鼠标事件，坐标实时解析）。"""
from __future__ import annotations

import json, os, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
OUT = ROOT / ".onefeed" / "ops-frames.json"

INIT = r"""
() => {
  if (window.__probe) return;
  const P = window.__probe = {frames: [], long: [], muts: 0, firstMut: -1, t0: 0, running: false};
  const rec = t => { if (!P.running) return; P.frames.push(t); requestAnimationFrame(rec); };
  try {
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) P.long.push({dur: e.duration, start: e.startTime});
    }).observe({type: 'longtask', buffered: true});
  } catch (e) {}
  new MutationObserver(ms => {
    if (!P.running) return;
    P.muts += ms.length;
    if (P.firstMut < 0) P.firstMut = performance.now();
  }).observe(document.documentElement, {subtree: true, childList: true, attributes: true, characterData: true});
  P.start = () => { P.frames = []; P.long = []; P.muts = 0; P.firstMut = -1; P.running = true; P.t0 = performance.now(); requestAnimationFrame(rec); };
  P.stop = () => {
    P.running = false;
    const f = P.frames, d = [];
    for (let i = 1; i < f.length; i++) d.push(f[i] - f[i - 1]);
    const s = [...d].sort((a, b) => a - b);
    const q = p => s.length ? s[Math.min(s.length - 1, Math.floor(s.length * p))] : null;
    const span = f.length > 1 ? f[f.length - 1] - f[0] : 0;
    const longIn = P.long.filter(l => l.start >= P.t0 - 20);
    return {n: d.length, fps: span > 0 ? +(d.length / (span / 1000)).toFixed(1) : null,
      p50: q(0.5) === null ? null : +q(0.5).toFixed(1),
      p95: q(0.95) === null ? null : +q(0.95).toFixed(1),
      max: d.length ? +Math.max(...d).toFixed(1) : null,
      jank33: d.filter(x => x > 33).length, slow16: d.filter(x => x > 16.7).length,
      longMs: +longIn.reduce((a, l) => a + l.dur, 0).toFixed(1), longN: longIn.length,
      longMax: longIn.length ? +Math.max(...longIn.map(l => l.dur)).toFixed(1) : 0,
      muts: P.muts, firstMutMs: P.firstMut < 0 ? null : +(P.firstMut - P.t0).toFixed(1), span: +span.toFixed(0)};
  };
}
"""

rows: list[dict] = []
errors: list[str] = []


def tap(page, cdp, xy):
    x, y = xy
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
    cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


SETTLE = """async () => {
  // 等上一轮的过渡/进场动画跑完再开测，否则前一个操作的尾巴会算到这一个头上
  const anims = document.getAnimations().filter(a => {
    const t = a.effect && a.effect.getTiming ? a.effect.getTiming() : null;
    return !t || t.iterations !== Infinity;
  });
  await Promise.all(anims.map(a => a.finished.catch(() => {})));
}"""


def measure(page, name, action, window_ms=800, note=""):
    page.evaluate(INIT)
    try:
        page.evaluate(SETTLE)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(80)
    page.evaluate("window.__probe.start()")
    t0 = time.perf_counter()
    err = None
    try:
        action()
    except Exception as e:  # noqa: BLE001
        err = str(e).split("\n")[0][:150]
    elapsed = (time.perf_counter() - t0) * 1000
    page.wait_for_timeout(window_ms)
    st = page.evaluate("window.__probe.stop()")
    row = {"op": name, "note": note, "actionMs": round(elapsed, 1), "err": err, **st}
    rows.append(row)
    flag = "!!" if err else ("!" if ((st["jank33"] or 0) >= 3 or (st["max"] or 0) > 60) else "  ")
    print(f"{flag} {name:22s} f={st['fps']} p95={st['p95']} max={st['max']} jank={st['jank33']} long={st['longMs']}/{st['longMax']} 首动={st['firstMutMs']} {err or ''}", flush=True)
    return row


def run(page, cdp, name, loc_fn, window_ms=800, note="", pre=None, scroll=True):
    try:
        loc = loc_fn(page)
        if scroll:
            loc.scroll_into_view_if_needed(timeout=4000)
        b = loc.bounding_box()
        if not b:
            raise RuntimeError("no box")
        xy = (b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    except Exception as e:  # noqa: BLE001
        rows.append({"op": name, "err": "locator: " + str(e).split("\n")[0][:120], "note": note})
        print(f"!! {name:22s} locator: {str(e).splitlines()[0][:100]}", flush=True)
        return
    if pre:
        pre()

    def act():
        tap(page, cdp, xy)
    measure(page, name, act, window_ms, note)


def settle_feed(page, qs="", wait=1200):
    page.goto(BASE + "/" + qs, wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(wait)


def pick_multi_image():
    raw = urllib.request.urlopen(BASE + "/api/feed?p=xiaohongshu&limit=30", timeout=20).read()
    data = json.loads(raw.decode("utf-8"))
    for it in data.get("items", []):
        if len(it.get("images") or []) >= 3:
            return it["id"]
    return None


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
    page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
    settle_feed(page)

    run(page, cdp, "left.collapse", lambda pg: pg.locator('button[title*="收起"], button[aria-label*="收起"]').first, 700, "240→64 回弹")
    page.wait_for_timeout(500)
    run(page, cdp, "left.expand", lambda pg: pg.locator('button[title*="展开"], button[aria-label*="展开"]').first, 700)

    run(page, cdp, "theme.flip", lambda pg: pg.locator('button[aria-label^="切换到"]').first, 1000, "clip-path 0.7s")
    page.wait_for_timeout(500)
    run(page, cdp, "theme.flip.back", lambda pg: pg.locator('button[aria-label^="切换到"]').first, 1000)
    page.wait_for_timeout(400)

    run(page, cdp, "chip.single", lambda pg: pg.locator('button:has-text("B 站")').first, 1000, "反色扫过 + 重排")
    page.wait_for_timeout(700)
    run(page, cdp, "chip.ctrl-multi", lambda pg: pg.locator('button:has-text("小红书")').first, 1000, "Ctrl 多选",
        pre=lambda: page.keyboard.down("Control"))
    page.keyboard.up("Control")
    page.wait_for_timeout(700)
    measure(page, "chip.esc-reset", lambda: page.keyboard.press("Escape"), 1000, "Esc 回全部")
    page.wait_for_timeout(700)
    measure(page, "chip.kbd-arrow", lambda: (page.keyboard.press("ArrowRight"), None), 400, "方向键挪焦点不选中")
    measure(page, "chip.kbd-enter", lambda: page.keyboard.press("Enter"), 900, "Enter 才选中")
    page.wait_for_timeout(600)

    run(page, cdp, "sort.hot", lambda pg: pg.locator('button[aria-pressed]:has-text("按热度")').first, 1000, "排序重排")
    page.wait_for_timeout(700)
    run(page, cdp, "range.today", lambda pg: pg.locator('button[aria-pressed]:has-text("今天")').first, 1000)
    page.wait_for_timeout(700)
    run(page, cdp, "range.all", lambda pg: pg.locator('button[aria-pressed]:has-text("全部")').first, 1000)
    page.wait_for_timeout(700)

    run(page, cdp, "cols.open", lambda pg: pg.locator('button[title*="每行显示"]').first, 600, "弹层进场")
    page.wait_for_timeout(400)
    run(page, cdp, "cols.pick4", lambda pg: pg.get_by_role("button", name="4 列", exact=True).first, 1000, "换列 + 锚点补偿")
    page.wait_for_timeout(700)
    measure(page, "cols.alt0", lambda: page.keyboard.press("Alt+0"), 1000, "Alt+0 回自动")
    page.wait_for_timeout(400)

    # 卡片微交互（坐标实时取）
    def card_xy():
        b = page.locator('a[href^="/item/"]').first.bounding_box()
        return (b["x"] + b["width"] / 2, b["y"] + 60)

    cx, cy = card_xy()
    measure(page, "card.hover", lambda: page.mouse.move(cx, cy), 500, "whileHover y-2")
    measure(page, "card.press", lambda: page.mouse.down(), 320, "whileTap 0.985")
    page.mouse.up()
    page.wait_for_timeout(500)

    # 先测菜单、再测星标：星标会把卡片换成「已保存」态，之后的定位容易失手
    run(page, cdp, "menu.open", lambda pg: pg.locator('button[aria-label="更多操作"]').first, 600, "portal + 首项 focus")
    page.wait_for_timeout(400)
    run(page, cdp, "menu.copy", lambda pg: pg.get_by_text("复制链接", exact=True).first, 800, "剪贴板 + toast")
    page.wait_for_timeout(1100)
    measure(page, "menu.esc", lambda: page.keyboard.press("Escape"), 500)
    page.wait_for_timeout(400)
    run(page, cdp, "card.star", lambda pg: pg.locator('button[aria-label="稍后再看"]').first, 800, "乐观 + aria-pressed")
    page.wait_for_timeout(900)

    # 筛选框
    settle_feed(page, "", 1100)
    measure(page, "filter.focus", lambda: page.locator("input[placeholder]").first.click(), 400)
    page.wait_for_timeout(200)
    measure(page, "filter.type", lambda: page.keyboard.type("AI"), 500, "输入 + 解析胶囊")
    measure(page, "filter.submit", lambda: page.keyboard.press("Enter"), 1400, "提交 → 请求 → 重排")
    page.wait_for_timeout(900)

    # 切页
    settle_feed(page, "", 1000)
    run(page, cdp, "nav.to-item", lambda pg: pg.locator('a[href^="/item/"]').first, 1200, "VT 共享元素 0.42s")
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(1500)
    run(page, cdp, "nav.back", lambda pg: pg.locator('button:has-text("返回")').first, 1200, "back 转场")
    page.wait_for_timeout(900)

    # 详情
    settle_feed(page, "?p=bilibili", 900)
    run(page, cdp, "item.from-feed", lambda pg: pg.locator('a[href^="/item/"]').first, 1200)
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(2600)
    run(page, cdp, "item.tab.source", lambda pg: pg.locator('button[aria-pressed]:has-text("原文")').first, 800, "tab .rise 重放")
    page.wait_for_timeout(500)
    run(page, cdp, "item.tab.summary", lambda pg: pg.locator('button[aria-pressed]:has-text("AI 总结")').first, 800)
    page.wait_for_timeout(500)
    run(page, cdp, "item.fav.open", lambda pg: pg.locator('button:has-text("收藏")').first, 800, "对话框 + 锁滚动")
    page.wait_for_timeout(400)
    measure(page, "item.fav.esc", lambda: page.keyboard.press("Escape"), 600, "关闭 + 还焦点")
    page.wait_for_timeout(500)
    run(page, cdp, "item.copy", lambda pg: pg.locator('button:has-text("复制链接")').first, 800, "图标变绿 2s")
    page.wait_for_timeout(1300)
    run(page, cdp, "agent.open", lambda pg: pg.locator('button[aria-label="打开 AI 助手"]').first, 900, "sheet 220ms")
    page.wait_for_timeout(600)
    measure(page, "agent.esc", lambda: page.keyboard.press("Escape"), 700)
    page.wait_for_timeout(400)

    # 灯箱：多图条目
    mid = pick_multi_image()
    print("multi-image item:", mid, flush=True)
    if mid:
        page.goto(BASE + "/item/" + urllib.parse.quote(mid, safe=""), wait_until="load")
        page.wait_for_timeout(3000)
        n = page.locator("[data-lb-index]").count()
        print("lightbox thumbs:", n, flush=True)
        if n:
            run(page, cdp, "lightbox.open", lambda pg: pg.locator("[data-lb-index]").first, 900, "VT 缩略图→大图")
            page.wait_for_timeout(700)
            measure(page, "lightbox.next", lambda: page.keyboard.press("ArrowRight"), 600)
            page.wait_for_timeout(400)
            measure(page, "lightbox.esc", lambda: page.keyboard.press("Escape"), 800)

    # 无限滚动 + 回顶
    settle_feed(page, "", 1400)
    measure(page, "feed.scroll-end", lambda: page.evaluate("window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})"), 2600, "触底→more→追加")
    page.wait_for_timeout(1000)
    if page.locator('button[title*="回到顶部"], button[aria-label*="回到顶部"]').count():
        run(page, cdp, "feed.scrolltop", lambda pg: pg.locator('button[title*="回到顶部"], button[aria-label*="回到顶部"]').first, 1500, "smooth 回顶")
    page.wait_for_timeout(1100)

    run(page, cdp, "topbar.refresh", lambda pg: pg.locator('button[aria-label="刷新全部平台"]').first, 1800, "乐观 running + 进度")
    page.wait_for_timeout(2000)
    measure(page, "help.open", lambda: page.keyboard.press("?"), 700)
    page.wait_for_timeout(400)
    measure(page, "help.esc", lambda: page.keyboard.press("Escape"), 500)

    # 1280 抽屉
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 860}, device_scale_factor=1)
    page2 = ctx2.new_page()
    cdp2 = ctx2.new_cdp_session(page2)
    page2.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
    page2.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
    settle_feed(page2, "", 1100)
    run(page2, cdp2, "drawer.open", lambda pg: pg.locator('button[title*="右侧栏"]').first, 800, "240ms 抽屉")
    page2.wait_for_timeout(600)
    tabs = page2.locator("[data-shell-drawer] [role=tab], [data-shell-drawer] button")
    print("drawer controls:", tabs.count(), flush=True)
    measure(page2, "drawer.esc", lambda: page2.keyboard.press("Escape"), 700)
    page2.wait_for_timeout(500)
    measure(page2, "drawer.key-open", lambda: page2.keyboard.press("]"), 800)
    page2.wait_for_timeout(500)
    measure(page2, "drawer.key-close", lambda: page2.keyboard.press("]"), 700)

    browser.close()

OUT.write_text(json.dumps({"rows": rows, "errors": errors}, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n=== 汇总 ===")
janky = [r for r in rows if not r.get("err") and (((r.get("jank33") or 0) >= 3) or ((r.get("max") or 0) > 60))]
print("操作数:", len(rows), "| 卡顿:", len(janky))
for r in janky:
    print(f"  {r['op']}: max={r['max']} jank={r['jank33']} long={r.get('longMs')}/{r.get('longMax')} note={r['note']}")
for r in rows:
    if r.get("err"):
        print("  失败:", r["op"], r["err"])
for e in dict.fromkeys(errors):
    print("  console:", e)
print("写盘:", OUT)
