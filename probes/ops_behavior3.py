
import os, sys, json, time
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"; PROBE = "http://127.0.0.1:8801"
out=[]
def check(n, c, d=""):
    out.append({"name": n, "ok": bool(c), "detail": str(d)[:400]})
    print(("PASS " if c else "FAIL ")+n+("  :: "+str(d)[:300] if d else ""), flush=True)
def act(pg):
    return pg.evaluate("""() => { const a=document.activeElement; return a ? a.tagName+'|'+(a.innerText||'').replace(/\s+/g,' ').trim().slice(0,18) : 'none'; }""")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width":1440,"height":900})
    pg = ctx.new_page()

    # A. 灯箱
    try:
        r = pg.goto(PROBE + "/item/xiaohongshu%3Anote%3A6aefeb59000000001802c758", wait_until="load")
        pg.wait_for_timeout(3200)
        n = pg.locator("[data-lb-index]").count()
        check("多图条目渲染缩略图", n >= 2, n)
        if n:
            pg.locator("[data-lb-index]").first.click()
            pg.wait_for_timeout(900)
            info = pg.evaluate("""() => ({ role: document.querySelectorAll('[role=dialog]').length,
               overflow: getComputedStyle(document.body).overflow, imgs: document.querySelectorAll('img').length })""")
            check("灯箱打开且有 dialog 语义", info["role"] >= 1, info)
            check("灯箱锁滚动", info["overflow"] == "hidden", info["overflow"])
            before = pg.evaluate("() => document.querySelectorAll('img[src]').length")
            pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(500)
            after = pg.evaluate("""() => { const a = document.activeElement; return {tag: a && a.tagName, txt: document.body.innerText.includes('/') }; }""")
            pg.keyboard.press("Escape"); pg.wait_for_timeout(600)
            check("Esc 关闭灯箱并解锁", pg.evaluate("() => getComputedStyle(document.body).overflow") != "hidden")
            check("关闭后焦点回缩略图", "IMG" in act(pg) or "BUTTON" in act(pg), act(pg))
    except Exception as e:
        check("灯箱流程", False, str(e).split("\n")[0][:140])

    # B. 收藏 Ctrl+Enter
    try:
        pg.goto(BASE + "/?p=bilibili", wait_until="load")
        pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1000)
        pg.locator('a[href^="/item/"]').first.click(); pg.wait_for_url("**/item/**", timeout=15000); pg.wait_for_timeout(2400)
        btn = pg.get_by_role("button", name="收藏", exact=True).first
        st0 = pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').replace(/\s+/g,'')==='收藏'); return b?{ap:b.getAttribute('aria-pressed'),t:b.innerText.trim()}:null; }""")
        check("收藏按钮有 aria-pressed", bool(st0 and st0["ap"] in ("false","true")), st0)
        btn.click(); pg.wait_for_timeout(500)
        pg.evaluate("""() => document.querySelector('[role=dialog] textarea').focus()""")
        pg.keyboard.type("留着以后翻")
        pg.wait_for_timeout(400)
        save = pg.evaluate("""() => { const d=document.querySelector('[role=dialog]'); const b=[...d.querySelectorAll('button')].find(x=>x.innerText.trim()==='保存'); return b?{dis:b.disabled,t:b.innerText.trim()}:null; }""")
        check("填备注后保存可用", bool(save and not save["dis"]), save)
        pg.keyboard.press("Control+Enter"); pg.wait_for_timeout(1200)
        check("Ctrl+Enter 保存并关闭", pg.locator('[role=dialog]').count()==0, pg.evaluate("() => document.querySelectorAll('[role=dialog]').length"))
        st1 = pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').replace(/\s+/g,'')==='已收藏'||(x.innerText||'').replace(/\s+/g,'')==='收藏'); return b?{ap:b.getAttribute('aria-pressed'),t:b.innerText.trim()}:null; }""")
        check("收藏状态更新为已收藏", bool(st1 and "已收藏" in st1["t"] and st1["ap"]=="true"), st1)
    except Exception as e:
        check("收藏 Ctrl+Enter 流程", False, str(e).split("\n")[0][:140])

    # C. 市场卸载 + 撤销
    try:
        pg.goto(BASE + "/market", wait_until="load"); pg.wait_for_timeout(2400)
        before = pg.evaluate("() => document.body.innerText.includes('已装')")
        n0 = pg.locator('button:has-text("卸载")').count()
        check("市场有卸载按钮", n0 > 0, n0)
        if n0:
            title0 = pg.locator('button:has-text("卸载")').first.evaluate("(e) => e.closest('div[class*=rise], article, li')?.innerText?.slice(0,40) || e.parentElement.parentElement.innerText.slice(0,60)")
            pg.locator('button:has-text("卸载")').first.click(); pg.wait_for_timeout(700)
            dlg = pg.evaluate("""() => { const d=document.querySelector('[role=dialog]'); return d?{txt:d.innerText.replace(/\s+/g,' ').slice(0,90), btns:[...d.querySelectorAll('button')].map(b=>b.innerText.trim()), focusInside:d.contains(document.activeElement)}:null; }""")
            check("卸载有确认框", bool(dlg), dlg)
            pg.evaluate("""() => { const d=document.querySelector('[role=dialog]'); const b=[...d.querySelectorAll('button')].find(x=>/卸载|确认|移除/.test(x.innerText)&&x.innerText.trim()!=='取消'); if(b) b.click(); }""")
            pg.wait_for_timeout(1000)
            undo = pg.evaluate("""() => { const e=[...document.querySelectorAll('div')].filter(x=>(x.innerText||'').includes('撤销')).pop(); if(!e) return null;
               const r=e.getBoundingClientRect(); return {t:(e.innerText||'').replace(/\s+/g,' ').slice(0,50), y:Math.round(r.y), h:Math.round(r.height), pos:getComputedStyle(e).position}; }""")
            check("卸载后出现撤销条", bool(undo), undo)
            if undo:
                pg.evaluate("""() => { const e=[...document.querySelectorAll('button')].find(x=>/撤销/.test(x.innerText)); if(e) e.click(); }""")
                pg.wait_for_timeout(1000)
                back = pg.locator('button:has-text("卸载")').count()
                check("撤销后插件恢复", back >= n0, {"before": n0, "after": back})
    except Exception as e:
        check("市场卸载撤销流程", False, str(e).split("\n")[0][:140])

    # D. Agent 一次真实问答的时延与流畅度
    try:
        pg.goto(BASE + "/", wait_until="load")
        pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1200)
        pg.keyboard.press("/"); pg.wait_for_timeout(800)
        inp = pg.locator('[data-agent-surface="sheet"] input[type=text]').first
        inp.wait_for(state="visible", timeout=8000)
        pg.evaluate("""() => { window.__lt=[]; new PerformanceObserver(l=>{for(const e of l.getEntries()) window.__lt.push(Math.round(e.duration));}).observe({entryTypes:['longtask']}); }""")
        inp.click(); pg.keyboard.type("找两条 B 站讲 AI 的视频，各写一句总结")
        t0 = time.perf_counter(); pg.keyboard.press("Enter")
        samples = []
        first_busy = first_text = None
        for i in range(200):
            s = pg.evaluate("""() => { const el=document.querySelector('[data-agent-surface="sheet"]'); if(!el) return {gone:true};
               const t=el.innerText; const btn=el.querySelector('button[aria-label*=停止], button[title*=停止]');
               const sq = el.querySelector('svg.lucide-square');
               return {txt:t, stop: !!btn || !!sq, len: t.length}; }""")
            if s.get("gone"): break
            if first_busy is None and s["stop"]: first_busy = (time.perf_counter()-t0)*1000
            if first_text is None and ("步" in s["txt"] or "翻" in s["txt"] or "条" in s["txt"] or "要点" in s["txt"]): first_text = (time.perf_counter()-t0)*1000
            samples.append((round((time.perf_counter()-t0)*1000), s["len"], s["stop"]))
            if "停下" in s["txt"] or "翻到" in s["txt"] or ("条。" in s["txt"] and s["len"] > 60) or i > 180:
                break
            time.sleep(0.15)
        lt = pg.evaluate("() => window.__lt || []")
        final = pg.evaluate("""() => { const el=document.querySelector('[data-agent-surface="sheet"]'); return el ? el.innerText.replace(/\s+/g,' ').slice(0,400) : ''; }""")
        check("发送后出现停止键（忙碌反馈）", first_busy is not None, f"{first_busy and round(first_busy)}ms")
        check("有可见进展文本", first_text is not None, f"{first_text and round(first_text)}ms")
        check("流式期间无长任务堆积", len([x for x in lt if x > 200]) <= 2, lt[:12])
        print("  最终文本:", final[:260], flush=True)
        print("  采样点:", samples[:14], "...共", len(samples), flush=True)
        # 停止键
        pg.keyboard.press("Escape"); pg.wait_for_timeout(700)
        closed = pg.evaluate("""() => { const el=document.querySelector('[data-agent-surface="sheet"]'); return !el || getComputedStyle(el).opacity==='0' || el.getBoundingClientRect().height===0; }""")
        check("Esc 收起 Agent 面板", closed)
    except Exception as e:
        check("Agent 真实问答流程", False, str(e).split("\n")[0][:140])

    b.close()
ok=sum(1 for r in out if r["ok"])
print(f"\n=== {ok}/{len(out)} 通过 ===")
for r in out:
    if not r["ok"]: print("  FAIL:", r["name"], "::", r["detail"])
(ROOT/".onefeed"/"ops-behavior3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
