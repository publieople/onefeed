"""知乎登录 + 信息流回放探针（CDP 常驻 Chrome）。

用法：
  uv run python probes/zhihu_cdp.py qr      # 打开知乎首页，截二维码
  uv run python probes/zhihu_cdp.py check   # 看 cookie 与当前 URL
  uv run python probes/zhihu_cdp.py watch   # 等登录成功后抓推荐流响应
"""
from __future__ import annotations

import json
import sys
import time

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9334"
OUT = "design"


def _connect(p):
    browser = p.chromium.connect_over_cdp(CDP)
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return browser, ctx, page


def has_login(ctx, page) -> bool:
    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    return bool(cookies.get("z_c0"))


def mode_qr() -> None:
    with sync_playwright() as p:
        browser, ctx, page = _connect(p)
        page.goto("https://www.zhihu.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        print("url:", page.url)
        # 找二维码：data:image 的 img，或 canvas
        box = None
        for sel in ['img[src^="data:image"]', "canvas"]:
            for el in page.query_selector_all(sel):
                bb = el.bounding_box()
                if bb and bb["width"] > 100 and bb["height"] > 100:
                    box = bb
                    print("qr element", sel, bb)
                    break
            if box:
                break
        if box is None:
            print("no qr element; screenshot whole viewport")
            page.screenshot(path=f"{OUT}/zhihu-cdp-full.png")
        else:
            pad = 10
            clip = {
                "x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                "width": box["width"] + pad * 2, "height": box["height"] + pad * 2,
            }
            page.screenshot(path=f"{OUT}/zhihu-cdp-qr.png", clip=clip)
            print("saved design/zhihu-cdp-qr.png", clip)
        page.bring_to_front()
        print("LOGIN_OK" if has_login(ctx, page) else "NOT_LOGGED_IN")


def mode_check() -> None:
    with sync_playwright() as p:
        browser, ctx, page = _connect(p)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        print("url:", page.url)
        print("cookies:", len(cookies), "z_c0:", bool(cookies.get("z_c0")))
        print("LOGIN_OK" if cookies.get("z_c0") else "NOT_LOGGED_IN")


def mode_watch(timeout: int = 300) -> None:
    """登录后打开首页，把推荐流的响应整段截下来。"""
    with sync_playwright() as p:
        browser, ctx, page = _connect(p)
        if not has_login(ctx, page):
            print("NOT_LOGGED_IN")
            return
        captured: list[dict] = []

        def on_response(resp):
            url = resp.url
            if "/api/v3/feed/topstory/recommend" in url or "/api/v3/moments" in url:
                try:
                    body = resp.text()
                except Exception as exc:  # noqa: BLE001
                    body = f"<read fail: {exc}>"
                captured.append({"url": url, "status": resp.status, "len": len(body), "body": body[:4000]})

        page.on("response", on_response)
        page.goto("https://www.zhihu.com/", wait_until="domcontentloaded", timeout=60000)
        deadline = time.time() + timeout
        while time.time() < deadline and not captured:
            page.wait_for_timeout(2000)
        print("captured:", len(captured))
        for i, item in enumerate(captured[:3]):
            print(f"--- #{i} {item['status']} len={item['len']}")
            print(item["url"][:160])
            print(item["body"][:1200].replace("\n", " "))
        with open(f"{OUT}/zhihu-feed-sample.json", "w", encoding="utf-8") as fh:
            json.dump(captured, fh, ensure_ascii=False, indent=2)
        print("saved design/zhihu-feed-sample.json")



def mode_await(timeout: int = 600) -> None:
    """等扫码 → 登录成功后立刻打开首页，抓推荐流响应。"""
    with sync_playwright() as p:
        browser, ctx, page = _connect(p)
        page.bring_to_front()
        deadline = time.time() + timeout
        ok = False
        while time.time() < deadline:
            if has_login(ctx, page):
                ok = True
                break
            page.wait_for_timeout(3000)
        print("LOGIN_OK" if ok else "TIMEOUT_NO_LOGIN", flush=True)
        if not ok:
            return
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        print("cookies after login:", len(cookies), flush=True)
        captured: list[dict] = []

        def on_response(resp):
            url = resp.url
            if "/api/v3/feed/topstory/recommend" in url or "/api/v3/moments" in url:
                try:
                    body = resp.text()
                except Exception as exc:  # noqa: BLE001
                    body = f"<read fail: {exc}>"
                captured.append({"url": url, "status": resp.status, "len": len(body), "body": body[:6000]})
                print("CAPTURED", resp.status, url[:120], len(body), flush=True)

        page.on("response", on_response)
        page.goto("https://www.zhihu.com/", wait_until="domcontentloaded", timeout=60000)
        wait_until = time.time() + 40
        while time.time() < wait_until and not captured:
            page.wait_for_timeout(2000)
        # 往下滚一点，触发更多推荐
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(4000)
        print("total captured:", len(captured), flush=True)
        with open(f"{OUT}/zhihu-feed-sample.json", "w", encoding="utf-8") as fh:
            json.dump(captured, fh, ensure_ascii=False, indent=2)
        if captured:
            item = captured[0]
            print("first status:", item["status"], "len:", item["len"], flush=True)
            print(item["body"][:800].replace("\n", " "), flush=True)
        print("saved design/zhihu-feed-sample.json", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    {"qr": mode_qr, "check": mode_check, "watch": mode_watch, "await": mode_await}[mode]()
