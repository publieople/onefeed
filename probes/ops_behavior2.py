
"""交互行为审计 2：收藏对话框、热键穿透、设置页保存条、市场撤销、Agent 流式、灯箱、移动端。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
PROBE = "http://127.0.0.1:8801"
out: list[dict] = []

def check(name, cond, detail=""):
    out.append({"name": name, "ok": bool(cond), "detail": str(detail)[:400]})
    print(("PASS " if cond else "FAIL ") + name + ("  :: " + str(detail)[:260] if detail else ""), flush=True)

def act(page):
    return page.evaluate("""() => { const a = document.activeElement; if (!a) return 'none';
      return a.tagName + '|' + ((a.innerText||'').replace(/\s+/g,' ').trim().slice(0,20)) + '|' + (a.getAttribute('role')||'') + '|' + (a.getAttribute('aria-label')||''); }""")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("  !!pageerror", str(e)[:160], flush=True))

    # ---- 1. 收藏对话框 ----
    try:
        page.goto(BASE + "/?p=bilibili", wait_until="load")
        page.wait_for_selector('a[href^="/item/"]', timeout=25000)
        page.wait_for_timeout(1000)
        page.locator('a[href^="/item/"]').first.click()
        page.wait_for_url("**/item/**", timeout=15000)
        page.wait_for_timeout(2400)
        page.get_by_role("button", name="收藏", exact=True).first.click()
        page.wait_for_timeout(500)
        has = page.locator('[role=dialog]').count()
        check("收藏对话框打开", has >= 1, has)
        inside = page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); return d ? d.contains(document.activeElement) : false; }""")
        check("焦点进入对话框", inside, act(page))
        check("锁 body 滚动", page.evaluate("() => getComputedStyle(document.body).overflow") in ("hidden", "clip"), page.evaluate("() => getComputedStyle(document.body).overflow"))
        ml = page.evaluate("""() => { const t = document.querySelector('[role=dialog] textarea'); return t ? [t.maxLength, t.value.length] : null; }""")
        check("备注 maxlength=200", ml and ml[0] == 200, ml)
        save_dis = page.evaluate("""() => { const d = document.querySelector('[role=dialog]');
          const b = [...d.querySelectorAll('button')].find(x => (x.innerText||'').includes('收藏') && (x.innerText||'').trim() !== '取消');
          return b ? {t: (b.innerText||'').trim(), dis: b.disabled} : null; }""")
        check("备注为空时保存禁用", bool(save_dis and save_dis["dis"]), save_dis)
        page.keyboard.type("测试备注")
        page.wait_for_timeout(300)
        save2 = page.evaluate("""() => { const d = document.querySelector('[role=dialog]');
          const b = [...d.querySelectorAll('button')].find(x => (x.innerText||'').includes('收藏') && (x.innerText||'').trim() !== '取消');
          return b ? {t: (b.innerText||'').trim(), dis: b.disabled} : null; }""")
        check("有备注后保存可用", bool(save2 and not save2["dis"]), save2)
        inside_tab = []
        for _ in range(8):
            page.keyboard.press("Tab")
            page.wait_for_timeout(70)
            inside_tab.append(page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); return d ? d.contains(document.activeElement) : false; }"""))
        check("Tab 不逃出对话框", all(inside_tab), inside_tab)
        page.keyboard.press("Control+Enter")
        page.wait_for_timeout(900)
        check("Ctrl+Enter 保存并关闭", page.locator('[role=dialog]').count() == 0)
        pressed = page.get_by_role("button", name="已收藏").count()
        check("收藏按钮变已收藏态", pressed >= 1, pressed)
        check("保存后焦点回到收藏按钮", "收藏" in act(page), act(page))
        # 移出（如果存在）
        page.wait_for_timeout(400)
    except Exception as e:
        check("收藏对话框流程", False, str(e).split("\n")[0][:150])

    # ---- 2. 热键穿透：无输入框的确认框 ----
    try:
        page.goto(BASE + "/market", wait_until="load")
        page.wait_for_timeout(2000)
        rm = page.locator('button:has-text("移除")')
        if rm.count():
            rm.first.click()
            page.wait_for_timeout(600)
            check("市场移除确认框", page.locator('[role=dialog]').count() >= 1)
            check("确认框有输入框", page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); return d ? !!d.querySelector('input,textarea') : false; }"""),
                  page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); return d ? d.innerText.slice(0,60) : null; }"""))
            page.keyboard.press("?")
            page.wait_for_timeout(500)
            help_open = page.evaluate("""() => document.body.innerText.includes('快捷键') && document.querySelectorAll('[role=dialog]').length""")
            check("确认框打开时 ? 不叠加弹出帮助面板", help_open == 1, help_open)
            page.keyboard.press("[")
            page.wait_for_timeout(500)
            w = page.evaluate("""() => { const e = document.querySelector('aside, [class*=left]'); return 0; }""")
            sw = page.evaluate("() => document.documentElement.getBoundingClientRect().width")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            check("Esc 关闭确认框（不误关别的东西）", page.locator('[role=dialog]').count() == 0)
        else:
            check("市场有移除按钮", False, 0)
    except Exception as e:
        check("市场确认框流程", False, str(e).split("\n")[0][:150])

    # ---- 3. 设置页数字输入 + 保存条 vs toast ----
    try:
        page.goto(BASE + "/settings", wait_until="load")
        page.wait_for_timeout(2200)
        page.locator('button:has-text("采集与排序")').first.click()
        page.wait_for_timeout(700)
        nums = page.locator('input[type=number]')
        check("数字输入可用", nums.count() >= 3, nums.count())
        first = nums.first
        before = first.input_value()
        first.fill("")
        page.wait_for_timeout(300)
        check("清空后不出现 NaN/空值", first.input_value() not in ("", "NaN"), repr(first.input_value()))
        first.fill(before or "12")
        page.wait_for_timeout(300)
        # 制造 dirty
        nums.nth(1).fill("31")
        page.wait_for_timeout(400)
        bar = page.evaluate("""() => { const els = [...document.querySelectorAll('div')].filter(e => (e.innerText||'').includes('有未保存的改动'));
          if (!els.length) return null; const r = els[els.length-1].getBoundingClientRect();
          return {y: Math.round(r.y), h: Math.round(r.height), x: Math.round(r.x)}; }""")
        check("保存条出现", bool(bar), bar)
        page.locator('button:has-text("重新检查")').first.click()
        page.wait_for_timeout(900)
        note = page.evaluate("""() => [...document.querySelectorAll('div')].filter(e => String(e.className).includes('bottom-6'))
          .map(e => { const r = e.getBoundingClientRect(); return {t: (e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,20), y: Math.round(r.y), z: getComputedStyle(e).zIndex}; })""")
        check("设置页有底部浮层（toast/保存条）", bool(note), note)
        overlap = bool(bar) and any(abs(n["y"] - bar["y"]) < 30 for n in note)
        check("toast 与保存条同位置重叠", overlap, {"bar": bar, "note": note})
        # 放弃改动
        disc = page.locator('button:has-text("放弃")')
        if disc.count():
            disc.first.click()
            page.wait_for_timeout(600)
            check("放弃后保存条消失", not page.evaluate("""() => [...document.querySelectorAll('div')].some(e => (e.innerText||'').includes('有未保存的改动'))"""))
    except Exception as e:
        check("设置页保存条流程", False, str(e).split("\n")[0][:150])

    # ---- 4. 市场撤销条 ----
    try:
        page.goto(BASE + "/market", wait_until="load")
        page.wait_for_timeout(2200)
        btns = page.locator('button:has-text("移除")')
        if btns.count():
            btns.first.click()
            page.wait_for_timeout(500)
            # 确认
            conf = page.evaluate("""() => { const d = document.querySelector('[role=dialog]'); if (!d) return null;
              return [...d.querySelectorAll('button')].map(b => (b.innerText||'').trim()); }""")
            page.evaluate("""() => { const d = document.querySelector('[role=dialog]');
              const b = [...d.querySelectorAll('button')].find(x => /移除|删除|确定/.test(x.innerText||''));
              if (b) b.click(); }""")
            page.wait_for_timeout(900)
            undo = page.evaluate("""() => { const e = [...document.querySelectorAll('div')].find(x => (x.innerText||'').includes('撤销'));
              if (!e) return null; const r = e.getBoundingClientRect(); return {t: (e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,40), y: Math.round(r.y), h: Math.round(r.height)}; }""")
            check("移除后出现撤销条", bool(undo), {"confirmButtons": conf, "undo": undo})
            page.wait_for_timeout(5200)
            gone = page.evaluate("""() => ![...document.querySelectorAll('div')].some(x => (x.innerText||'').includes('撤销'))""")
            check("撤销条 5 秒后自动消失", gone)
    except Exception as e:
        check("市场撤销流程", False, str(e).split("\n")[0][:150])

    # ---- 5. Agent 流式（真实一次调用）----
    try:
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector('a[href^="/item/"]', timeout=25000)
        page.wait_for_timeout(1200)
        page.keyboard.press("/")
        page.wait_for_timeout(700)
        surf = page.evaluate("""() => { const s = document.querySelector('[data-agent-surface]');
          const c = s && s.querySelector('textarea, input[type=text]');
          return s ? {surface: s.getAttribute('data-agent-surface'), tag: c && c.tagName, ph: c && c.placeholder} : null; }""")
        check("斜杠唤出 Agent 面板", bool(surf), surf)
        if surf and surf["tag"]:
            page.evaluate("""() => document.querySelector('[data-agent-surface] textarea, [data-agent-surface] input[type=text]').focus()""")
            page.keyboard.type("找两条 B 站讲 AI 的视频，各写一句总结")
            t0 = time.perf_counter()
            page.keyboard.press("Enter")
            first_feedback = None
            stop_seen = False
            for i in range(160):
                st = page.evaluate("""() => { const s = document.querySelector('[data-agent-surface]');
                  const txt = s ? s.innerText : '';
                  const stopping = s ? !!s.querySelector('svg.lucide-square, svg.lucide-loader-circle, svg.lucide-loader-2, [aria-label*=停止]') : false;
                  return {txt: txt.slice(0, 400), stopping}; }""")
                if not first_feedback and ("听着" in st["txt"] or "翻" in st["txt"] or "步" in st["txt"] or "要点" in st["txt"] or "B 站" in st["txt"]):
                    first_feedback = (time.perf_counter() - t0) * 1000
                stop_seen = stop_seen or st["stopping"]
                if "停下" in st["txt"] or "翻到" in st["txt"] or "条。" in st["txt"]:
                    break
                time.sleep(0.2)
            check("发送后有即时忙碌反馈", True, f"stop_visible={stop_seen}")
            check("首条可见进展", first_feedback is not None, f"{first_feedback and round(first_feedback)}ms")
            stream_txt = page.evaluate("() => (document.querySelector('[data-agent-surface]')||{}).innerText || ''")
            print("  流式文本:", stream_txt[:300].replace("\n", " / "), flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
            check("Esc 收起 Agent", page.evaluate("() => !document.querySelector('[data-agent-surface=\"sheet\"]') || getComputedStyle(document.querySelector('[data-agent-surface=\"sheet\"]')).opacity === '0'"))
    except Exception as e:
        check("Agent 流式流程", False, str(e).split("\n")[0][:150])

    # ---- 6. 404 ----
    try:
        page.goto(BASE + "/nope", wait_until="load")
        page.wait_for_timeout(800)
        t = page.inner_text("body")
        check("404 页有出口", ("信息流" in t or "回" in t), t[:60].replace("\n", " / "))
        page.get_by_role("link", name="回信息流").first.click() if page.get_by_role("link", name="回信息流").count() else None
        page.wait_for_timeout(1200)
        check("404 能回到信息流", "/item" not in page.url, page.url)
    except Exception as e:
        check("404 流程", False, str(e).split("\n")[0][:150])

    # ---- 7. 灯箱（8801 多图库）----
    try:
        page2 = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page2.goto(PROBE + "/item/" + "xiaohongshu%3Anote%3A6aefeb59000000001802c758", wait_until="load")
        page2.wait_for_timeout(3000)
        n = page2.locator("[data-lb-index]").count()
        check("多图条目渲染缩略图", n >= 2, n)
        if n:
            page2.locator("[data-lb-index]").first.click()
            page2.wait_for_timeout(800)
            lb = page2.evaluate("""() => { const d = document.querySelector('[class*=z-\\\\[60\\\\]]');
              return {dialogs: document.querySelectorAll('[role=dialog]').length, bodyLock: getComputedStyle(document.body).overflow,
                      bigImgs: document.querySelectorAll('img').length}; }""")
            check("灯箱打开", lb["dialogs"] >= 1 or lb["bigImgs"] >= n, lb)
            page2.keyboard.press("ArrowRight")
            page2.wait_for_timeout(400)
            page2.keyboard.press("Escape")
            page2.wait_for_timeout(600)
            check("Esc 关闭灯箱", page2.evaluate("() => getComputedStyle(document.body).overflow") != "hidden")
    except Exception as e:
        check("灯箱流程", False, str(e).split("\n")[0][:150])

    # ---- 8. 移动端 390 ----
    try:
        ctx3 = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
        m = ctx3.new_page()
        m.goto(BASE + "/", wait_until="load")
        m.wait_for_selector('a[href^="/item/"]', timeout=25000)
        m.wait_for_timeout(1800)
        res = m.evaluate("""() => {
          const de = document.documentElement;
          const small = [...document.querySelectorAll('button, a[href], input')].filter(e => { const r = e.getBoundingClientRect();
            const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && (r.width < 40 || r.height < 40); })
            .slice(0, 10).map(e => ({t: (e.innerText||e.getAttribute('aria-label')||e.title||'').trim().slice(0,14), w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height)}));
          return {sw: de.scrollWidth, iw: innerWidth, cards: document.querySelectorAll('a[href^="/item/"]').length,
                  cols: getComputedStyle(document.querySelector('[data-content]') || de).gridTemplateColumns, small};
        }""")
        check("移动端无横向溢出", res["sw"] <= res["iw"] + 1, res["sw"] - res["iw"])
        check("移动端有卡片", res["cards"] > 0, res["cards"])
        print("  移动端小目标:", json.dumps(res["small"], ensure_ascii=False)[:420], flush=True)
        print("  栅格:", res["cols"][:120], flush=True)
    except Exception as e:
        check("移动端流程", False, str(e).split("\n")[0][:150])

    b.close()

ok = sum(1 for r in out if r["ok"]); total = len(out)
print(f"\n=== {ok}/{total} 通过 ===")
for r in out:
    if not r["ok"]:
        print("  FAIL:", r["name"], "::", r["detail"])
(ROOT / ".onefeed" / "ops-behavior2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
