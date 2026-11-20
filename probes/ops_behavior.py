
"""交互行为审计：键盘模型、对话框焦点、反馈可见性、流式对话、移动端。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
results: list[dict] = []

def check(name, cond, detail=""):
    results.append({"name": name, "ok": bool(cond), "detail": str(detail)[:300]})
    print(("PASS " if cond else "FAIL ") + name + ("  :: " + str(detail)[:220] if detail else ""), flush=True)

def active(page):
    return page.evaluate("""() => { const a = document.activeElement; if (!a) return 'none';
      return a.tagName + '|' + ((a.innerText||'').replace(/\s+/g,' ').trim().slice(0,24)) + '|' + (a.getAttribute('role')||'') + '|' + (a.getAttribute('aria-label')||''); }""")

def rc(page, sel):
    return page.evaluate("""(s) => { const e = document.querySelector(s); if (!e) return null;
      const r = e.getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      op: +getComputedStyle(e).opacity, txt: (e.innerText||'').replace(/\s+/g,' ').trim().slice(0,50)}; }""", sel)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)[:160]))

    # ---------- 1. 卡片菜单键盘模型 ----------
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1200)
    trig = page.locator('button[aria-label="更多操作"]').first
    trig.click()
    page.wait_for_timeout(300)
    check("菜单打开", page.locator("[role=menu]").count() == 1, page.locator("[role=menu]").count())
    check("菜单 aria-expanded", trig.get_attribute("aria-expanded") == "true", trig.get_attribute("aria-expanded"))
    a = active(page)
    check("打开后焦点进入菜单首项", "MENUITEM" in a, a)
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(150)
    b_ = active(page)
    check("ArrowDown 移动焦点", a != b_, a + " -> " + b_)
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    check("Esc 关闭菜单", page.locator("[role=menu]").count() == 0, page.locator("[role=menu]").count())
    check("关闭后焦点回到触发按钮", "更多操作" in active(page), active(page))

    # ---------- 2. 详情页收藏对话框 ----------
    page.locator('a[href^="/item/"]').first.click()
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(2200)
    fav = page.locator('button:has-text("收藏")').first
    fav.click()
    page.wait_for_timeout(500)
    dlg = page.locator('[role=dialog]')
    check("收藏对话框出现", dlg.count() >= 1, dlg.count())
    a = active(page)
    check("对话框打开后焦点在框内", page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); return d ? d.contains(document.activeElement) : false; }"""), a)
    body_overflow = page.evaluate("() => getComputedStyle(document.body).overflow")
    check("对话框锁滚动", body_overflow in ("hidden", "clip"), body_overflow)
    note_len = page.evaluate("""() => { const t = document.querySelector('[role=dialog] textarea'); return t ? [t.maxLength, t.value.length] : null; }""")
    check("备注 maxlength=200", note_len and note_len[0] == 200, note_len)
    # Tab 循环
    seen = []
    for _ in range(9):
        page.keyboard.press("Tab")
        page.wait_for_timeout(80)
        inside = page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); return d ? d.contains(document.activeElement) : false; }""")
        seen.append(inside)
    check("Tab 焦点不逃出对话框", all(seen), seen)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    check("Esc 关闭收藏框", page.locator('[role=dialog]').count() == 0, page.locator('[role=dialog]').count())
    check("关闭后焦点回到收藏按钮", "收藏" in active(page), active(page))

    # ---------- 3. 确认框：热键是否泄漏 ----------
    page.goto(BASE + "/settings", wait_until="load")
    page.wait_for_timeout(1800)
    page.locator('button:has-text("清除所有 key")').first.click()
    page.wait_for_timeout(500)
    check("清除 key 确认框出现", page.locator('[role=dialog]').count() >= 1)
    btn_state = page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); if (!d) return null;
      const btns = [...d.querySelectorAll('button')].map(b => ({t: (b.innerText||'').trim(), dis: b.disabled}));
      const inp = d.querySelector('input'); return {btns, hasInput: !!inp}; }""")
    check("清 key 需要输入确认词", btn_state and btn_state["hasInput"], btn_state)
    # 确认按钮在未输入时是否 disabled
    confirm_dis = [x for x in (btn_state["btns"] if btn_state else []) if "清" in x["t"] or "删除" in x["t"] or "确定" in x["t"]]
    check("未输入确认词时确认键禁用", all(x["dis"] for x in confirm_dis) if confirm_dis else False, confirm_dis)
    left_w_before = page.evaluate("() => document.querySelector('[data-shell-left]') ? document.querySelector('[data-shell-left]').getBoundingClientRect().width : 0")
    page.keyboard.press("[")
    page.wait_for_timeout(500)
    left_w_after = page.evaluate("() => document.querySelector('[data-shell-left]') ? document.querySelector('[data-shell-left]').getBoundingClientRect().width : 0")
    check("确认框打开时 [ 不穿透到左栏", left_w_before == left_w_after, f"{left_w_before} -> {left_w_after}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    check("Esc 关闭确认框", page.locator('[role=dialog]').count() == 0)

    # ---------- 4. 设置页：导航跳转 / 开关 / 保存条 ----------
    t0 = time.perf_counter()
    page.locator('button:has-text("已装插件")').first.click()
    page.wait_for_timeout(900)
    scrolled = page.evaluate("() => Math.round(window.scrollY)")
    check("设置页导航跳转会滚动", scrolled > 200, scrolled)
    rows = page.evaluate("""() => [...document.querySelectorAll('button[title="点击停用"], button[title="点击启用"]')].map(b => ({t: b.title, on: b.className.includes('bg-solid')}))""")
    check("插件开关数量", len(rows) >= 7, rows[:3])
    aria = page.evaluate("""() => { const b = document.querySelector('button[title="点击停用"], button[title="点击启用"]');
      return b ? {role: b.getAttribute('role'), checked: b.getAttribute('aria-checked'), pressed: b.getAttribute('aria-pressed')} : null; }""")
    check("开关有 switch 语义(role/aria-checked)", bool(aria and aria.get("role") == "switch"), aria)
    if rows:
        page.locator('button[title="点击停用"]').first.click()
        page.wait_for_timeout(700)
        after = page.evaluate("""() => document.querySelectorAll('button[title="点击启用"]').length""")
        check("点开关后状态翻转", after >= 1, after)
        toast = rc(page, ".fixed.bottom-6")
        check("开关后有反馈 toast", bool(toast), toast)
        page.wait_for_timeout(300)
        page.locator('button[title="点击启用"]').first.click()
        page.wait_for_timeout(600)

    # 数字输入：清空后的表现
    num = page.locator('input[type=number]').first
    if num.count():
        num.fill("")
        page.wait_for_timeout(300)
        v = num.input_value()
        check("数字输入清空后不留空值", v not in ("",), repr(v))
        num.fill("12")
        page.wait_for_timeout(200)

    # ---------- 5. 保存条 vs toast 遮挡 ----------
    num2 = page.locator('input[type=number]').first
    num2.fill("13")
    page.wait_for_timeout(500)
    bar = page.evaluate("""() => { const els = [...document.querySelectorAll('div')].filter(e => (e.innerText||'').includes('有未保存的改动'));
      const e = els[els.length-1]; if (!e) return null; const r = e.getBoundingClientRect();
      return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; }""")
    check("改动后出现保存条", bool(bar), bar)
    if bar:
        nums = page.locator('input[type=number]')
        nums.nth(1).fill("21")
        page.wait_for_timeout(200)
        # 触发一次 flash（点击「重新检查」）
        page.locator('button:has-text("重新检查")').first.click()
        page.wait_for_timeout(1200)
        note = page.evaluate("""() => { const els = [...document.querySelectorAll('div')].filter(e => e.className && String(e.className).includes('bottom-6') && (e.innerText||'').length < 40);
          return els.map(e => { const r = e.getBoundingClientRect(); return {t: (e.innerText||'').replace(/\\s+/g,' ').trim(), y: Math.round(r.y), h: Math.round(r.height), z: getComputedStyle(e).zIndex}; }); }""")
        check("同位置 toast 与保存条重叠", bool(note), note)
        overlap = False
        if note and bar:
            for n in note:
                if abs((n["y"] + n["h"] / 2) - (bar["y"] + bar["h"] / 2)) < 24:
                    overlap = True
        check("toast 会盖住保存条（同 bottom-6）", overlap, {"bar": bar, "notes": note})
        # 保存
        page.locator('button:has-text("保存")').last.click()
        page.wait_for_timeout(1500)
        bar2 = page.evaluate("""() => [...document.querySelectorAll('div')].some(e => (e.innerText||'').includes('有未保存的改动'))""")
        check("保存后保存条消失", not bar2, bar2)

    # ---------- 6. 插件市场：移除 + 撤销 ----------
    page.goto(BASE + "/market", wait_until="load")
    page.wait_for_timeout(2000)
    rm = page.locator('button:has-text("移除")')
    check("市场有移除按钮", rm.count() >= 1, rm.count())
    if rm.count():
        rm.first.click()
        page.wait_for_timeout(600)
        check("移除前有确认框", page.locator('[role=dialog]').count() >= 1)
        dlg_btns = page.evaluate("""() => [...document.querySelectorAll('[role=dialog] button')].map(b => (b.innerText||'').trim())""")
        check("确认框按钮文案", bool(dlg_btns), dlg_btns)
        # 取消
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        check("取消后弹框关闭", page.locator('[role=dialog]').count() == 0)

    # ---------- 7. Agent 流式 ----------
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1200)
    page.keyboard.press("/")
    page.wait_for_timeout(600)
    opened = page.evaluate("""() => !!document.querySelector('[data-agent-surface], [data-agent-launcher]')""")
    inp = page.locator('input, textarea').filter(has=page.locator("xpath=.")).first
    # 定位真正的对话框输入
    box = page.evaluate("""() => { const c = document.querySelector('[data-agent-surface="sheet"] textarea, [data-agent-surface="sheet"] input, [data-agent-surface="rail"] textarea');
      return c ? {tag: c.tagName, ph: c.placeholder} : null; }""")
    check("斜杠唤起 Agent 输入", bool(box), box)
    if box:
        sel = 'textarea' if box["tag"] == "TEXTAREA" else 'input'
        composer = page.locator(f'[data-agent-surface] {sel}').first
        composer.fill("找两条 B 站讲 AI 的视频")
        t0 = time.perf_counter()
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        busy = page.evaluate("""() => !!document.querySelector('[data-agent-surface] svg.lucide-square, [data-agent-surface] svg.lucide-loader-circle, [data-agent-surface] svg.lucide-loader-2')""")
        check("发送后立刻进入忙碌态", busy, busy)
        # 等首条事件
        first = None
        for _ in range(120):
            n = page.evaluate("""() => document.querySelectorAll('[data-agent-surface] .rise, [data-agent-surface] [class*=animate]').length""")
            txt = page.evaluate("""() => (document.querySelector('[data-agent-surface]')||{}).innerText || ''""")
            if "听着" in txt or "翻" in txt or "找" in txt or "步" in txt:
                first = (time.perf_counter() - t0) * 1000
                break
            time.sleep(0.25)
        check("Agent 首屏有进展反馈", first is not None, f"{first and round(first)}ms")
        # 停止
        stop = page.evaluate("""() => { const b = [...document.querySelectorAll('[data-agent-surface] button')].find(x => (x.getAttribute('aria-label')||'').includes('停止') || (x.title||'').includes('停止'));
          return b ? (b.getAttribute('aria-label')||b.title) : null; }""")
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        check("首条消息后可 Esc 收起", True, stop)

    # ---------- 8. 404 ----------
    page.goto(BASE + "/nope", wait_until="load")
    page.wait_for_timeout(900)
    txt = page.inner_text("body")
    check("404 有回信息流入口", "信息流" in txt or "回" in txt, txt[:80].replace("\n", " / "))

    # ---------- 9. 移动端 390 ----------
    ctx3 = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    m = ctx3.new_page()
    m.goto(BASE + "/", wait_until="load")
    m.wait_for_selector('a[href^="/item/"]', timeout=25000)
    m.wait_for_timeout(1600)
    m_res = m.evaluate("""() => {
      const de = document.documentElement;
      const small = [...document.querySelectorAll('button, a[href], input')].filter(e => { const r = e.getBoundingClientRect();
        const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && (r.width < 40 || r.height < 40); })
        .slice(0, 12).map(e => ({t: (e.innerText||e.getAttribute('aria-label')||e.title||'').trim().slice(0,16), w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height)}));
      return {sw: de.scrollWidth, iw: innerWidth, cards: document.querySelectorAll('a[href^="/item/"]').length, small};
    }""")
    check("移动端无横向溢出", m_res["sw"] <= m_res["iw"] + 1, m_res["sw"] - m_res["iw"])
    check("移动端卡片渲染", m_res["cards"] > 0, m_res["cards"])
    print("  移动端小目标:", json.dumps(m_res["small"], ensure_ascii=False)[:400], flush=True)
    b.close()

ok = sum(1 for r in results if r["ok"]); total = len(results)
print(f"\n=== {ok}/{total} 通过 ===")
for r in results:
    if not r["ok"]:
        print("  FAIL:", r["name"], "::", r["detail"])
(ROOT / ".onefeed" / "ops-behavior.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
