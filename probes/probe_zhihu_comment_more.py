# -*- coding: utf-8 -*-
"""探针 v4：专栏页评论区有哪些可点的东西（找「加载更多/展开」按钮）。"""
import json, sys, pathlib
ROOT = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import _find_chrome, UA
ensure_temp_env()
from playwright.sync_api import sync_playwright

COOKIES = json.loads((ROOT / ".onefeed" / "cookies" / "zhihu.json").read_text(encoding="utf-8"))
PREP = [{"name": c["name"], "value": c.get("value",""), "domain": c.get("domain") or ".zhihu.com",
         "path": c.get("path") or "/", "httpOnly": bool(c.get("httpOnly")),
         "secure": bool(c.get("secure")), "sameSite": c.get("sameSite") or "Lax"}
        for c in (COOKIES.get("cookies") or []) if c.get("name")]

hits = []
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(browser_profile("zhihu")), executable_path=_find_chrome(), headless=True,
        locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled"])
    ctx.add_cookies(PREP)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", lambda r: hits.append(r.url.split("?")[0]) if "comment_v5" in r.url else None)
    page.goto("https://zhuanlan.zhihu.com/p/652468637", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    for _ in range(8):
        page.mouse.wheel(0, 2400); page.wait_for_timeout(700)
    labels = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('button, a, div[role="button"]').forEach(el => {
        const t = (el.innerText || '').trim();
        if (!t || t.length > 30) return;
        if (/更多|展开|查看全部|加载|评论/.test(t)) out.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,60), text: t});
      });
      return out.slice(0, 25);
    }""")
    print("LABELS:", json.dumps(labels, ensure_ascii=False)[:2000])
    print("HITS:", json.dumps(sorted(set(hits))[:10], ensure_ascii=False))
    ctx.close()
