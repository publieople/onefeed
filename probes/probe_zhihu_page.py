
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import UA, _find_chrome
from playwright.sync_api import sync_playwright

Q = "https://www.zhihu.com/question/2104528020287354223"
ensure_temp_env()
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(user_data_dir=str(browser_profile("zhihu_probe")),
        executable_path=_find_chrome(), headless=True, locale="zh-CN",
        viewport={"width":1440,"height":900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled"])
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    resp = pg.goto(Q, wait_until="domcontentloaded", timeout=60000)
    print("status:", resp.status if resp else None, "final:", pg.url[:90])
    pg.wait_for_timeout(4000)
    html = pg.content()
    print("html len:", len(html), "title:", pg.title()[:60])
    print("WAF marker 40362:", "40362" in html, "| 请求存在异常:", "请求存在异常" in html)
    print("has __INITIAL_STATE__:", "__INITIAL_STATE__" in html, "| has js-initialData:", "js-initialData" in html)
    info = pg.evaluate("""() => {
      const s = window.__INITIAL_STATE__ || {};
      const out = {keys: Object.keys(s).slice(0, 14)};
      try {
        const ent = s.entities || {};
        out.entityKeys = Object.keys(ent).slice(0, 6);
        const ans = ent.answers || {};
        const akeys = Object.keys(ans);
        out.answers = akeys.length;
        if (akeys.length) { const a = ans[akeys[0]];
          out.firstAnswer = {len: (a.content||'').length, excerpt: (a.excerpt||'').slice(0,80), author: ((a.author||{}).name), vote: (a.voteupCount)}; }
        const q = (ent.questions || {});
        const qk = Object.keys(q);
        if (qk.length) out.question = {title: (q[qk[0]].title||'').slice(0,60), answerCount: q[qk[0]].answerCount, detailLen: (q[qk[0]].detail||'').length};
      } catch (e) { out.err = String(e).slice(0, 80); }
      return out; }""")
    print("state:", json.dumps(info, ensure_ascii=False)[:900])
    Path("probes/tmp_zhihu_question.html").write_text(html, encoding="utf-8")
    ctx.close()
