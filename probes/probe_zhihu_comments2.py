# -*- coding: utf-8 -*-
"""探针 v3：知乎专栏页与回答页的评论接口 URL 与字段。"""
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

def run_case(name, url, click_text):
    hits = []
    def on_resp(resp):
        if "/comment_v5/" in resp.url:
            try:
                j = resp.json()
                rows = j.get("data") or []
                first = rows[0] if rows else {}
                hits.append({"url": resp.url.split("?")[0], "total": (j.get("counts") or {}).get("total_counts"),
                             "n": len(rows), "like": first.get("like_count"),
                             "child": first.get("child_comment_count"), "content": str(first.get("content") or "")[:60]})
            except Exception as exc:
                hits.append({"url": resp.url.split("?")[0], "err": str(exc)[:80]})
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(browser_profile("zhihu")), executable_path=_find_chrome(), headless=True,
            locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA,
            args=["--disable-blink-features=AutomationControlled"])
        ctx.add_cookies(PREP)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_resp)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        for _ in range(5):
            page.mouse.wheel(0, 2400); page.wait_for_timeout(800)
        if click_text:
            try:
                btn = page.query_selector('button:has-text("条评论")')
                if btn:
                    btn.click(timeout=4000); page.wait_for_timeout(4000)
            except Exception as exc:
                print(name, "CLICK_ERR", str(exc)[:100])
        page.wait_for_timeout(2000)
        print(name, "=>", json.dumps(hits[:3], ensure_ascii=False)[:900])
        ctx.close()

run_case("ARTICLE", "https://zhuanlan.zhihu.com/p/652468637", False)
run_case("ANSWER", "https://www.zhihu.com/question/544559630/answer/2105312425360807218", True)
