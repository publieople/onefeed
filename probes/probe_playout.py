"""刷新演出探针：用拦截的接口喂一轮「有 5 条新内容」的刷新，看相位机的真实时序。

为什么要拦截：真实刷新要不要拿到新条目、要跑多久、平台会不会冷却，全都不确定，
而这些不确定性恰好是这条动效唯一不能出错的地方 —— 演出必须在「确定有新内容」时才播。
"""
import json
import sys

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = "http://127.0.0.1:8799"

state = {
    "running": False,
    "phase": "idle",
    "started_at": 0,
    "finished_at": 0,
    "done": 0,
    "total": 0,
    "new_total": 0,
    "plugins": {},
}
ctrl = {"round": 0, "grown": 0, "progress_calls": 0, "fresh": 5}

# 侧通道：给页面里的采样器读，避免反复跨进程求值
def arm(page):
    page.evaluate(
        """() => {
      window.__log = [];
      const tick = () => {
        const holder = document.querySelector('[data-vt-item]');
        const grid = holder ? holder.parentElement : null;
        const bar = document.querySelector('[data-refresh-bar]');
        window.__log.push({
          t: Math.round(performance.now()),
          out: document.querySelectorAll('[data-out="1"]').length,
          freshNew: document.querySelectorAll('[data-in="new"]').length,
          carry: document.querySelectorAll('[data-in="carry"]').length,
          cards: document.querySelectorAll('[data-vt-item]').length,
          badges: document.querySelectorAll('.card-fresh').length,
          h: grid ? Math.round(grid.getBoundingClientRect().height) : 0,
          lock: grid ? grid.style.minHeight : '',
          bar: bar ? bar.textContent.trim().slice(0, 48) : '',
          pill: Array.from(document.querySelectorAll('button')).some((b) => b.textContent.includes('条新内容')),
          busy: grid ? grid.getAttribute('aria-busy') : '',
        });
        window.__raf = requestAnimationFrame(tick);
      };
      tick();
    }"""
    )


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True)
    ctx = b.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900})
    # headless 的 document.visibilityState 是 hidden，而「后台标签页不播」是硬闸门
    ctx.add_init_script(
        """
      Object.defineProperty(Document.prototype, 'visibilityState', { get: () => 'visible', configurable: true });
      Object.defineProperty(Document.prototype, 'hidden', { get: () => false, configurable: true });
    """
    )
    page = ctx.new_page()

    def on_progress(route):
        if state["running"]:
            ctrl["progress_calls"] += 1
            if ctrl["progress_calls"] >= 1:
                # 第一次轮询就报「结束」：App 由此 ++reloadKey 并 ++refreshSeq
                state.update(
                    running=False,
                    phase="done",
                    done=1,
                    total=1,
                    finished_at=int(__import__("time").time()),
                    new_total=ctrl["fresh"],
                    plugins={"bilibili": {"status": "ok", "count": ctrl["fresh"], "new_count": ctrl["fresh"], "ms": 900, "label": "B 站", "error": ""}},
                )
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"state": state}))

    def on_refresh(route):
        import time as _t

        ctrl["round"] += 1
        ctrl["progress_calls"] = 0
        ctrl["grown"] = ctrl["round"]
        state.update(
            running=True,
            phase="fetching",
            started_at=int(_t.time()) - 3,
            finished_at=0,
            done=0,
            total=1,
            new_total=0,
            plugins={"bilibili": {"status": "running", "count": 0, "new_count": 0, "ms": 0, "label": "B 站", "error": ""}},
        )
        route.fulfill(status=202, content_type="application/json", body=json.dumps({"ok": True, "state": state}))

    def on_feed(route):
        resp = route.fetch()
        data = resp.json()
        if ctrl["grown"] and data.get("items"):
            need = ctrl["fresh"] * ctrl["grown"]
            base = data["items"][:3] or data["items"]
            extra = []
            for i in range(need):
                src = dict(base[i % len(base)])
                src["id"] = "probe:new:%d:%d" % (ctrl["grown"], i)
                src["title"] = "探针新条目 %d-%d" % (ctrl["grown"], i)
                src["count"] = 0
                extra.append(src)
            data["items"] = extra + data["items"]
            data["count"] = int(data.get("count") or 0) + len(extra)
        route.fulfill(response=resp, body=json.dumps(data), headers={"content-type": "application/json"})

    page.route("**/api/progress", on_progress)
    page.route("**/api/refresh", on_refresh)
    page.route("**/api/feed*", on_feed)

    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("[data-vt-item]", timeout=20000)
    page.wait_for_timeout(1600)  # 让 lastQueryAt 的 1.2s 冷却过去

    mode = sys.argv[1] if len(sys.argv) > 1 else "top"
    if mode == "few":
        ctrl["fresh"] = 1  # 1–2 条：轻量档，只弹一下，不许清场
    if mode == "bottom":
        arm(page)
        page.evaluate("() => window.scrollTo({top: 2400, behavior: 'instant'})")
        page.wait_for_timeout(300)
    else:
        arm(page)

    before = page.evaluate("() => document.querySelector('[data-vt-item]').parentElement.getBoundingClientRect().top")
    page.click('button[aria-label="刷新全部平台"]')
    # 轮询 1.6s 一拍 + 数据回来 + 收/留白/立/登场 ≈ 2.2s
    page.wait_for_timeout(4200 if mode == "top" else 2600)
    page.wait_for_timeout(1600)

    log = page.evaluate("() => window.__log")
    # 只看点完之后的那段
    frames = [f for f in log]
    if mode == "bottom":
        bar = [f for f in frames if f["pill"]][:3]
        print("PILL_FRAMES", json.dumps(bar, ensure_ascii=False))
        print("PILL_DID_NOT_COLLAPSE", all(f["out"] == 0 for f in frames))
        print("PILL_BADGE", page.evaluate("() => (Array.from(document.querySelectorAll('button')).find((b) => b.textContent.includes('条新内容')) || {}).textContent?.trim() || ''"))
        # 点胶囊：应当先回顶，再补一次登场（这一步最容易漏，漏了就永远只有胶囊）
        page.evaluate("() => (Array.from(document.querySelectorAll('button')).find((b) => b.textContent.includes('条新内容'))).click()")
        page.wait_for_timeout(2200)
        after = page.evaluate("() => window.__log")
        tail = after[len(frames):]
        print("PILL_CLICK_SCROLLY", page.evaluate("() => Math.round(window.scrollY)"))
        print("PILL_CLICK_SHOW", json.dumps({
            "peak_out": max((f["out"] for f in tail), default=0),
            "peak_new": max((f["freshNew"] for f in tail), default=0),
            "saw_reveal": any(f["freshNew"] for f in tail),
        }, ensure_ascii=False))
        print("PILL_CLICK_FINAL", page.evaluate("() => ({out: document.querySelectorAll('[data-out=\"1\"]').length, badges: document.querySelectorAll('.card-fresh').length, lock: document.querySelector('[data-vt-item]').parentElement.style.minHeight})"))
        ctx.close(); b.close(); raise SystemExit

    picked = [f for f in frames if f["out"] or f["freshNew"] or f["carry"] or f["lock"] or f["busy"] == "true"]
    phases = {
        "collapse_first": next((f["t"] for f in frames if f["out"]), None),
        "peak_out": max((f["out"] for f in frames), default=0),
        "first_new": next((f["t"] for f in frames if f["freshNew"]), None),
        "peak_new": max((f["freshNew"] for f in frames), default=0),
        "peak_carry": max((f["carry"] for f in frames), default=0),
        "lock_set": next((f["lock"] for f in frames if f["lock"]), ""),
        "height_min": min((f["h"] for f in picked), default=0),
        "height_max": max((f["h"] for f in picked), default=0),
        "cards_min": min((f["cards"] for f in frames if f["cards"]), default=0),
        "cards_max": max((f["cards"] for f in frames), default=0),
        "badges_peak": max((f["badges"] for f in frames), default=0),
    }
    print("PHASES", json.dumps(phases, ensure_ascii=False))
    print("BAR_RUNNING", next((f["bar"] for f in frames if "正在抓取" in f["bar"]), ""))
    print("BAR_DONE", next((f["bar"] for f in frames if "这一轮" in f["bar"]), ""))
    print("BAR_FINAL", page.evaluate("() => document.querySelector('[data-refresh-bar]')?.textContent.trim() || ''"))
    print("BAR_AFTER_SHOW", page.evaluate("() => (document.querySelector('[data-refresh-bar]')?.textContent || '').includes('刚放进来的') ? 'played' : ((document.querySelector('[data-refresh-bar]')?.textContent || '').includes('看新内容') ? 'STILL_OFFERS_REPLAY' : 'none')"))
    print("AFTER", json.dumps(page.evaluate("() => ({out: document.querySelectorAll('[data-out=\"1\"]').length, new: document.querySelectorAll('[data-in=\"new\"]').length, carry: document.querySelectorAll('[data-in=\"carry\"]').length, cards: document.querySelectorAll('[data-vt-item]').length, badges: document.querySelectorAll('.card-fresh').length, lock: document.querySelector('[data-vt-item]').parentElement.style.minHeight, top: document.querySelector('[data-vt-item]').getBoundingClientRect().top})"), ensure_ascii=False))
    if mode == "few":
        print("FEW", json.dumps({
            "peak_out": max((f["out"] for f in frames), default=0),
            "peak_new": max((f["freshNew"] for f in frames), default=0),
            "lock": next((f["lock"] for f in frames if f["lock"]), ""),
            "bar_played": page.evaluate("() => (document.querySelector('[data-refresh-bar]')?.textContent || '').includes('刚放进来的')"),
        }, ensure_ascii=False))
        ctx.close(); b.close(); raise SystemExit
    print("BEFORE_TOP", before)
    print("SERIES", json.dumps([{k: f[k] for k in ("t", "out", "freshNew", "carry", "h", "cards")} for f in picked[::6]][:30], ensure_ascii=False))
    page.screenshot(path=".onefeed/tmp/playout-end.png")
    ctx.close(); b.close()
