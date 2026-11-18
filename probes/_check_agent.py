import os, sys, time, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
os.environ["ONEFEED_HOME"] = str(ROOT / ".onefeed" / "tmp" / "agent-probe-home")
db = ROOT / ".onefeed" / "tmp" / "agent-probe.db"
for suf in ("", "-wal", "-shm"):
    Path(str(db) + suf).unlink(missing_ok=True)
from onefeed.store import Store
from onefeed import agent as agent_mod
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

now = int(time.time())
def item(iid, platform, kind, title, text, hours=0, duration=0, like=0, cluster=""):
    return {"id": iid, "platform": platform, "kind": kind, "title": title, "text": text,
            "author": "作者", "url": "https://x/" + iid, "published_at": now - hours * 3600,
            "duration": duration, "like": like, "cluster_id": cluster, "fetched_at": now}
store = Store(db)
store.upsert_items([
    item("b1", "bilibili", "video", "五分钟讲懂大模型推理", "AI 大模型 推理", 1, 300, 900),
    item("b2", "bilibili", "video", "本地部署 DeepSeek 实录", "显存 量化", 2, 1500, 200),
    item("x1", "xiaohongshu", "images", "用 AI 做了一张海报", "海报 出图", 3, 0, 0),
    item("b3", "bilibili", "video", "装机闲聊 said the main rail", "显卡", 4, 60, 5000),
])
captured = []
real_search = store.search_items
def wrapped(*a, **kw):
    rows = real_search(*a, **kw)
    captured.append(rows)
    return rows
store.search_items = wrapped

def scripted(messages, info):
    returned = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
    if not returned:
        return ModelResponse(parts=[ToolCallPart("search", {"terms": ["AI", "大模型"]})])
    tool_name = info.output_tools[0].name if info.output_tools else "final_result"
    ids = [r["id"] for r in captured[-1]]
    picks = [{"id": i, "why": "相关"} for i in ids]
    picks.append({"id": "ghost", "why": "编的 id"})
    return ModelResponse(parts=[ToolCallPart(tool_name, {"reply": "挑好了", "picks": picks})])

out = agent_mod.run(store, "B 站有什么 AI 的", model=FunctionModel(scripted), max_tools=4)
print("engine", out["engine"], "steps", out["steps"], "ms", out["ms"])
print("reply", out["reply"], "count", out["count"])
print("ids", [i["id"] for i in out["items"]])
print("plan", out["plan"])
print("understood", out["understood"], "tokens", out["tokens"])
assert out["engine"] == "agent" and out["steps"] == 1
assert "b3" not in [i["id"] for i in out["items"]], "假命中 b3 混进来了"
assert "ghost" not in [i["id"] for i in out["items"]], "编造的 id 必须被丢"
assert out["items"], "至少挑到一条"

# 零挑选：候选有，但模型决定不挑
def pick_none(messages, info):
    returned = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
    if not returned:
        return ModelResponse(parts=[ToolCallPart("search", {"terms": ["量子"]})])
    tool_name = info.output_tools[0].name if info.output_tools else "final_result"
    return ModelResponse(parts=[ToolCallPart(tool_name, {"reply": "库里没有量子计算的内容。", "picks": []})])
none = agent_mod.run(store, "找量子计算", model=FunctionModel(pick_none))
print("zero:", none["count"], none["reply"])
assert none["count"] == 0 and "量子" in none["reply"]

# 超时：脚本模型故意慢
def slow(messages, info):
    time.sleep(3)
    return ModelResponse(parts=[])
try:
    agent_mod.run(store, "慢", model=FunctionModel(slow), timeout=0.8)
    raise AssertionError("应该超时")
except TimeoutError as exc:
    print("timeout ok:", exc)
print("OK agent 层通过")
