# -*- coding: utf-8 -*-
"""探针：知乎回答详情页能不能拿到全文（api/v4/answers 或 js-initialData）。"""
import json, sys, pathlib
ROOT = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import _find_chrome, UA

ensure_temp_env()
from playwright.sync_api import sync_playwright

URL = "https://www.zhihu.com/question/544559630/answer/2105312425360807218"
data = json.loads((ROOT / ".onefeed" / "cookies" / "zhihu.json").read_text(encoding="utf-8"))
prepared = []
for c in data.get("cookies") or []:
    if not c.get("name"):
        continue
    prepared.append({"name": c["name"], "value": c.get("value", ""),
                     "domain": c.get("domain") or ".zhihu.com", "path": c.get("path") or "/",
                     "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
                     "sameSite": c.get("sameSite") or "Lax"})

profile = browser_profile("zhihu")
profile.mkdir(parents=True, exist_ok=True)
hits = []

def on_response(resp):
    if "/api/v4/answers/" in resp.url or "/api/v4/articles/" in resp.url:
        try:
            j = resp.json()
            hits.append({"url": resp.url, "keys": sorted(j.keys())[:12],
                         "content_len": len(str(j.get("content") or "")),
                         "excerpt_len": len(str(j.get("excerpt") or ""))})
        except Exception as exc:
            hits.append({"url": resp.url, "err": str(exc)})

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(profile), executable_path=_find_chrome(), headless=True,
        locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"],
    )
    ctx.add_cookies(prepared)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    print("URL:", page.url, "| TITLE:", page.title()[:60])
    print("HITS:", json.dumps(hits, ensure_ascii=False)[:1500])
    info = page.evaluate("""() => {
        const el = document.getElementById('js-initialData');
        if (!el) return { ok: false };
        const t = el.textContent || '';
        const s = JSON.parse(t);
        const ents = (s.initialState || {}).entities || {};
        const ans = ents.answers || {};
        const keys = Object.keys(ans);
        const first = keys.length ? ans[keys[0]] : null;
        return {
          ok: true, len: t.length, n_answers: keys.length,
          contentLen: first ? String(first.content || '').length : 0,
          author: first ? ((first.author || {}).name || '') : '',
          title: first ? (((first.question || {}).title) || '') : ''
        };
    }""")
    print("INITIAL:", json.dumps(info, ensure_ascii=False)[:600])
    ctx.close()
