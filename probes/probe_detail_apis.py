
import json, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
def req(url, data=None, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if headers: h.update(headers)
    body = json.dumps(data).encode() if data is not None else None
    if body: h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, resp.read()
    except Exception as e:
        return getattr(e, "code", -1), str(e).encode()

aid = "7707927071724486665"
for label, url, data in [
    ("JUEJIN-GET", f"https://api.juejin.cn/content_api/v1/article/detail?article_id={aid}", None),
    ("JUEJIN-POST-aid", "https://api.juejin.cn/content_api/v1/article/detail", {"aid": aid}),
    ("JUEJIN-POST-str", "https://api.juejin.cn/content_api/v1/article/detail", {"article_id": aid, "need_book": False}),
]:
    s, raw = req(url, data, headers={"Referer": f"https://juejin.cn/post/{aid}"})
    print(label, s, raw[:160])
    if s == 200 and b'"err_no":0' in raw:
        d = json.loads(raw).get("data") or {}
        info = d.get("article_info") or {}
        print("  mark_len:", len(info.get("mark_content") or ""), "title:", (info.get("title") or "")[:40])

# V2EX
s, raw = req("https://www.v2ex.com/api/topics/show.json?id=1257214")
t = json.loads(raw)[0]
print("V2EX", s, "content_len:", len(t.get("content") or ""), "replies(int):", t.get("replies"),
      "rendered_len:", len(t.get("content_rendered") or ""))

# XHS
cookie_path = r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\cookies\xiaohongshu.json"
try:
    data = json.load(open(cookie_path, encoding="utf-8"))
    raw_ck = data.get("cookies") if isinstance(data, dict) and "cookies" in data else data
    if isinstance(raw_ck, dict):
        names = list(raw_ck.keys()); ck = "; ".join(f"{k}={v}" for k, v in raw_ck.items())
    else:
        names = [c.get("name") for c in raw_ck]; ck = "; ".join(f"{c['name']}={c['value']}" for c in raw_ck if c.get("name"))
    print("XHS cookies:", names)
except Exception as e:
    ck = ""; print("no xhs cookie:", e)
s, raw = req("https://edith.xiaohongshu.com/api/sns/web/v1/feed",
             {"source_note_id": "6af770220000000024030e0e",
              "xsec_token": "ABjHJEX2MBEP3ThzGUz073xIfP43f5Ce5njpFkRwPQ9fE=",
              "xsec_source": "pc_feed"},
             headers={"Cookie": ck, "Origin": "https://www.xiaohongshu.com",
                      "Referer": "https://www.xiaohongshu.com/"})
print("XHS", s, raw[:260])
