
import json, urllib.request, time
def get(url, proxy=None):
    h = urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
    opener = urllib.request.build_opener(h)
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 Chrome/141"})
    t0=time.time()
    with opener.open(req, timeout=15) as r:
        return r.status, len(r.read()), round(time.time()-t0,2)
for url in ["https://www.v2ex.com/api/topics/hot.json"]:
    for p in [None, "http://127.0.0.1:7890"]:
        try:
            print(url, "proxy=", p, get(url, p))
        except Exception as e:
            print(url, "proxy=", p, "ERR", type(e).__name__, str(e)[:60])
