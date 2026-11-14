
import os, sys, json, time
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
WS = r"E:\Documents\deepseek-harness\default-workspace"
TMP = os.path.join(WS, "onefeed", ".onefeed", "tmp"); os.makedirs(TMP, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = TMP
from playwright.sync_api import sync_playwright

OUT = os.path.join(WS, "onefeed", "probes", "tmp_xhs_cookies_cdp.json")
LOG = os.path.join(WS, "onefeed", "probes", "tmp_xhs_watch.txt")
NAMES = ("a1","webId","web_session","web_session_sec","id_token","websectiga",
         "sec_poison_id","xsecappid","gid","abRequestId","webBuild","loadts")

def log(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

deadline = time.time() + 900
with sync_playwright() as p:
    log("WATCH start")
    while time.time() < deadline:
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            url = page.url
            ck = {c["name"]: c["value"] for c in ctx.cookies() if "xiaohongshu" in (c.get("domain") or "")}
            ws_ = ck.get("web_session", "")
            if "login" not in url:
                time.sleep(3)
                ck = {c["name"]: c["value"] for c in ctx.cookies() if "xiaohongshu" in (c.get("domain") or "")}
                sel = {k: v for k, v in ck.items() if k in NAMES}
                json.dump({"cookies": sel}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                log("LOGGED_IN url=%s keys=%s" % (url, ",".join(sorted(sel.keys()))))
                try:
                    page.screenshot(path=os.path.join(WS, "onefeed", "probes", "xhs_after_login_cdp.png"))
                except Exception:
                    pass
                break
            else:
                log("waiting url=%s ws=%s.." % (url, ws_[:8]))
        except Exception as exc:
            log("ERR %s %s" % (type(exc).__name__, str(exc)[:120]))
        time.sleep(4)
log("WATCH end")
