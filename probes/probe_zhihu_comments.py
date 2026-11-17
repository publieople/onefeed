# -*- coding: utf-8 -*-
"""探针 v2：抓 root_comment 的响应体结构（一条评论有哪些字段）。"""
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
grabbed = []

def slim(c):
    a = c.get("author") or {}
    return {
        "id": c.get("id"),
        "type": c.get("type"),
        "content_head": str(c.get("content") or "")[:120],
        "content_len": len(str(c.get("content") or "")),
        "author": a.get("name"),
        "author_id": a.get("id"),
        "author_url": a.get("url_token") or a.get("url"),
        "avatar": str(a.get("avatar_url") or "")[:60],
        "vote_count": c.get("vote_count"),
        "created_time": c.get("created_time"),
        "child_count": c.get("child_comment_count"),
        "child_comments": [slim(x) for x in (c.get("child_comments") or [])[:2]],
        "keys": sorted(c.keys()),
    }

def on_response(resp):
    if "/comment_v5/" not in resp.url or "root_comment" not in resp.url:
        return
    try:
        j = resp.json()
        rows = j.get("data") or []
        grabbed.append({
            "url": resp.url[:200],
            "counts": j.get("counts"),
            "n": len(rows),
            "first": slim(rows[0]) if rows else None,
            "paging": j.get("paging"),
        })
    except Exception as exc:
        grabbed.append({"url": resp.url[:120], "err": str(exc)[:100]})

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
    page.wait_for_timeout(4000)
    for i in range(6):
        page.mouse.wheel(0, 2400)
        page.wait_for_timeout(900)
    try:
        btn = page.query_selector("button:has-text('条评论')")
        if btn:
            btn.click(timeout=4000)
            page.wait_for_timeout(4000)
    except Exception as exc:
        print("CLICK_ERR:", str(exc)[:120])
    page.wait_for_timeout(2500)
    print("GRABBED:", json.dumps(grabbed[:2], ensure_ascii=False)[:4000])
    ctx.close()
