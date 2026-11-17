# -*- coding: utf-8 -*-
"""探专栏页 js-initialData 的实体结构。"""
import json, sys, pathlib
ROOT = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import _find_chrome, UA

ensure_temp_env()
from playwright.sync_api import sync_playwright

data = json.loads((ROOT / ".onefeed" / "cookies" / "zhihu.json").read_text(encoding="utf-8"))
prepared = [{"name": c["name"], "value": c.get("value", ""),
             "domain": c.get("domain") or ".zhihu.com", "path": c.get("path") or "/",
             "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
             "sameSite": c.get("sameSite") or "Lax"}
            for c in (data.get("cookies") or []) if c.get("name")]

profile = browser_profile("zhihu")
profile.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(profile), executable_path=_find_chrome(), headless=True,
        locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"])
    ctx.add_cookies(prepared)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://zhuanlan.zhihu.com/p/652468637", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    info = page.evaluate("""() => {
      const el = document.getElementById('js-initialData');
      if (!el) return { ok: false, href: location.href };
      const s = JSON.parse(el.textContent || '{}');
      const st = s.initialState || {};
      const ents = st.entities || {};
      const out = { ok: true, topKeys: Object.keys(s).slice(0, 10), stateKeys: Object.keys(st).slice(0, 20), entityGroups: {} };
      Object.keys(ents).forEach(function (k) {
        const g = ents[k] || {};
        out.entityGroups[k] = Object.keys(g).length;
      });
      const arts = ents.articles || {};
      const aks = Object.keys(arts);
      if (aks.length) {
        const a = arts[aks[0]] || {};
        out.article = {
          keys: Object.keys(a).slice(0, 30),
          id: String(a.id || ''),
          title: String(a.title || ''),
          contentLen: String(a.content || '').length,
          author: String((a.author || {}).name || ''),
          voteup: Number(a.voteupCount || 0),
          comment: Number(a.commentCount || 0)
        };
      }
      return out;
    }""")
    print(json.dumps(info, ensure_ascii=False)[:2500])
    ctx.close()
