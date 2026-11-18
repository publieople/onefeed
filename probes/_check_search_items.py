import os, sys, time
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
os.environ["ONEFEED_HOME"] = str(ROOT / ".onefeed" / "tmp" / "search-probe-home")
db = ROOT / ".onefeed" / "tmp" / "search-probe.db"
for suf in ("", "-wal", "-shm"):
    Path(str(db) + suf).unlink(missing_ok=True)
from onefeed.store import Store
now = int(time.time())
rows = []
def add(iid, title, text, author="作者", hours=0, duration=0, like=0, kind="video", platform="bilibili"):
    rows.append({"id": iid, "platform": platform, "kind": kind, "title": title, "text": text,
                 "author": author, "url": "https://x/" + iid, "published_at": now - hours * 3600,
                 "duration": duration, "like": like, "fetched_at": now})
add("b1", "五分钟讲懂大模型推理", "AI 大模型 推理 入门", hours=0, duration=300, like=500)
add("b2", "本地部署 DeepSeek 实录", "显存不够怎么办", hours=2, duration=1800, like=50)
add("b3", "今天聊聊装机", "显卡 装机 said the main rail mail", hours=6, duration=60, like=5000)
add("b4", "AI 绘图的三种做法", "Midjourney 与 Stable Diffusion", hours=1, duration=600, like=800)
add("x1", "用 AI 做了一张海报", "海报 出图", hours=1, kind="images", platform="xiaohongshu")
add("z1", "深度学习怎么找 idea 发论文", "科研 idea AI 大模型", hours=4, kind="article", platform="zhihu")
store = Store(db)
store.upsert_items(rows)

hits = store.search_items(terms=["AI"], limit=10)
print("AI hits:", [(h["id"], round(store._hit_score(["AI"], h), 2)) for h in hits])
assert not any(h["id"] == "b3" for h in hits), "假命中：AI 命中了 said/main/rail"
assert {h["id"] for h in hits} == {"b1", "b4", "x1", "z1"}, "应只命中真含 AI 的 4 条"

weighted = store.search_items(terms=["大模型"], limit=10)
print("大模型 hits:", [h["id"] for h in weighted])
assert weighted[0]["id"] == "b1", "标题命中（x3）应排前"
long = store.search_items(terms=["大模型"], limit=10, duration_min=900)
print("duration>=900:", [h["id"] for h in long])
assert long == [], "时长过滤要真生效"
hot = store.search_items(terms=["AI"], limit=10, like_min=600)
print("like>=600:", [h["id"] for h in hot])
assert [h["id"] for h in hot] == ["b4"], "点赞过滤要真生效"
multi = store.search_items(terms=["DeepSeek", "海报"], limit=10)
print("多词 OR:", [h["id"] for h in multi])
assert {h["id"] for h in multi} == {"b2", "x1"}, "多词是或关系"
none = store.search_items(terms=["量子计算"], limit=10)
print("无命中:", none)
assert none == [], "没有就说没有，不许凑数"
print("OK 检索层 6 项断言通过")
