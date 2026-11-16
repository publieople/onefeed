
import json, re, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
url = "https://juejin.cn/post/7707927071724486665"
r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
try:
    with urllib.request.urlopen(r, timeout=25) as resp:
        html = resp.read().decode("utf-8", "replace")
        print("STATUS", resp.status, "len", len(html))
except Exception as e:
    print("FAIL", getattr(e, "code", -1), e); raise SystemExit
for marker in ["mark_content", "article-content", "__NUXT__", "window.__INITIAL_STATE__", "class=\"article-area", "article_info"]:
    print(f"  {marker!r}:", html.count(marker))
m = re.search(r'<article[^>]*>(.*?)</article>', html, re.S)
if m:
    text = re.sub(r"<[^>]+>", "", m.group(1))
    print("  article tag len(html):", len(m.group(1)), "text len:", len(text.strip()))
    print("  preview:", text.strip()[:120].replace("\n", " "))
else:
    i = html.find("mark_content")
    print("  around mark_content:", html[max(0,i-80):i+200].replace("\n", " ") if i>0 else "n/a")
