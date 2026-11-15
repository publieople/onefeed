
import collections, os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP = os.path.join(ROOT, ".onefeed", "tmp")
os.makedirs(TMP, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = TMP

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8791")

JS = r"""
() => {
  const arts = [...document.querySelectorAll("article")];
  return arts.map((a) => {
    const r = a.getBoundingClientRect();
    const head = a.querySelector("header");
    const headTxt = head ? head.innerText.replace(/\s+/g, " ").trim() : "";
    const t = a.querySelector("h3");
    const img = a.querySelector("img");
    const media = a.querySelector("[data-media]");
    return {
      h: Math.round(r.height * 10) / 10,
      w: Math.round(r.width * 10) / 10,
      x: Math.round(r.x),
      y: Math.round(r.y),
      head: headTxt,
      title: t ? t.innerText.slice(0, 26) : "",
      hasImg: !!img,
      mediaH: media ? Math.round(media.getBoundingClientRect().height) : 0,
      alignSelf: getComputedStyle(a).alignSelf,
      gridH: a.parentElement ? Math.round(a.parentElement.getBoundingClientRect().height) : 0,
    };
  });
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(1500)
    cards = pg.evaluate(JS)
    b.close()

KIND = re.compile(r"(视频|图文|文章|动态|榜单)")
print("cards:", len(cards))
bykind = collections.defaultdict(list)
for c in cards:
    m = KIND.search(c["head"])
    bykind[m.group(1) if m else "?"].append(c)

print("\n== 每类高度 ==")
for k, v in sorted(bykind.items(), key=lambda kv: -len(kv[1])):
    hs = sorted(x["h"] for x in v)
    print(f"{k:3s} n={len(v):3d} h min={hs[0]:6.1f} p50={hs[len(hs)//2]:6.1f} max={hs[-1]:6.1f} mediaH={sorted({x['mediaH'] for x in v})} 带图={sum(1 for x in v if x['hasImg'])}/{len(v)}")

rows = collections.defaultdict(list)
for c in cards:
    rows[c["y"]].append(c)
print("\n== 按行 ==")
for y in sorted(rows)[:7]:
    row = sorted(rows[y], key=lambda c: c["x"])
    kinds = [ (KIND.search(c["head"]).group(1) if KIND.search(c["head"]) else "?") for c in row]
    print(f"y={y:5d} 行高={row[0]['gridH']:6.1f} 卡高={[c['h'] for c in row]} 类型={kinds}")

print("\n== align-self ==", dict(collections.Counter(c["alignSelf"] for c in cards)))
