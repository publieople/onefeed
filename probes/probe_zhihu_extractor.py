# -*- coding: utf-8 -*-
"""验证宿主内置提取器 zhihu.question 在「回答页」上的产出。"""
import json, sys, pathlib
ROOT = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import _find_chrome, UA, EXTRACTORS

ensure_temp_env()
from playwright.sync_api import sync_playwright

data = json.loads((ROOT / ".onefeed" / "cookies" / "zhihu.json").read_text(encoding="utf-8"))
prepared = [{"name": c["name"], "value": c.get("value", ""),
             "domain": c.get("domain") or ".zhihu.com", "path": c.get("path") or "/",
             "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
             "sameSite": c.get("sameSite") or "Lax"}
            for c in (data.get("cookies") or []) if c.get("name")]

targets = [
    ("answer", "https://www.zhihu.com/question/544559630/answer/2105312425360807218"),
    ("article", "https://zhuanlan.zhihu.com/p/652468637"),
]
profile = browser_profile("zhihu")
profile.mkdir(parents=True, exist_ok=True)
js = EXTRACTORS["zhihu.question"]["js"]

with sync_playwright() as pw:
    for kind, url in targets:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile), executable_path=_find_chrome(), headless=True,
            locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"])
        ctx.add_cookies(prepared)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4500)
        v = page.evaluate(js)
        print("==", kind, "==", page.url[:70])
        if not v or not v.get("ok"):
            print("   FAIL", json.dumps(v, ensure_ascii=False)[:300])
        else:
            q = v.get("question") or {}
            ans = v.get("answers") or []
            print("   question:", q.get("title", "")[:50], "| answerCount", q.get("answerCount"))
            for a in ans[:2]:
                print("   answer by", a.get("author"), "voteup", a.get("voteup"),
                      "contentLen", len(a.get("content") or ""))
                print("      head:", (a.get("content") or "")[:120].replace("\n", " "))
        ctx.close()
