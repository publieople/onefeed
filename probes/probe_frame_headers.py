
import urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
urls = {
  "xiaohongshu": "https://www.xiaohongshu.com/explore/6af770220000000024030e0e?xsec_token=ABjHJEX2MBEP3ThzGUz073xIfP43f5Ce5njpFkRwPQ9fE%3D&xsec_source=pc_feed",
  "douyin": "https://www.douyin.com/video/7708298410222553765",
  "zhihu": "https://www.zhihu.com/question/2105217978186691603",
  "bilibili": "https://www.bilibili.com/video/BV15Gsj6iEaz",
  "bilibili_player": "https://player.bilibili.com/player.html?bvid=BV15Gsj6iEaz&page=1",
}
for name, url in urls.items():
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            h = {k.lower(): v for k, v in resp.headers.items()}
            print(name, resp.status,
                  "| xfo:", h.get("x-frame-options", "-"),
                  "| csp:", (h.get("content-security-policy") or "-")[:200])
    except Exception as e:
        code = getattr(e, "code", -1)
        hh = getattr(e, "headers", None)
        h = {k.lower(): v for k, v in (hh.items() if hh else [])}
        print(name, "ERR", code,
              "| xfo:", h.get("x-frame-options", "-"),
              "| csp:", (h.get("content-security-policy") or "-")[:200])
