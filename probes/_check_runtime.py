import json, pathlib, sys, tempfile, time
sys.path.insert(0, r"E:\Documents\deepseek-harness\default-workspace\onefeed")
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from onefeed.store import Store
from onefeed import agent_runtime as rt

tmp = pathlib.Path(tempfile.mkdtemp())
store = Store(tmp / "t.db")
now = int(time.time())
store.upsert_items([
    {"id": "b1", "platform": "bilibili", "kind": "video", "title": "AI 编程实战", "like_count": 900, "published_at": now - 3600, "duration": 400},
    {"id": "b2", "platform": "bilibili", "kind": "video", "title": "大模型评测", "like_count": 300, "published_at": now - 7200},
    {"id": "x1", "platform": "xiaohongshu", "kind": "images", "title": "AI 出图", "like_count": 50, "published_at": now - 600},
])

def scripted(messages, info):
    returned = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
    if not returned:
        return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["AI"], "platforms": ["B站"]})])
    got = returned[-1].content
    rows = got.get("items") if isinstance(got, dict) else []
    name = info.output_tools[0].name if info.output_tools else "final_result"
    return ModelResponse(parts=[ToolCallPart(name, {
        "reply": f"挑了 {len(rows)} 条。",
        "picks": [{"id": r["id"], "why": "标题命中"} for r in rows[:2]] + [{"id": "ghost", "why": "编的"}],
    })])

res = rt.run(store, "找点 AI 的", chain=[{"name": "stub", "model": "stub"}],
             model=FunctionModel(scripted), timeout=20)
print("RESULT engine", res["engine"], "count", res["count"], "ids", [i["id"] for i in res["items"]])
print("reply", res["reply"], "| steps", res["steps"], "| ms", res["ms"], "| understood", res["understood"])
print("plan", res["plan"])
run = store.get_agent_run(res["run_id"])
print("STATUS", run["status"], "events", len(run["events"]))
print("KINDS", [(e["seq"], e["kind"], e["name"]) for e in run["events"]])
print("STEPS_AFTER replay", len(rt.events_after(store, res["run_id"], 0)))
print("SSE frames", sum(1 for _ in rt.sse_stream(store, res["run_id"])))

# 收藏动作
saved = rt.run(store, "把 b1 存起来", chain=[{"name": "stub", "model": "stub"}],
               model=FunctionModel(lambda m, i: ModelResponse(parts=[ToolCallPart(
                   i.output_tools[0].name if i.output_tools else "final_result",
                   {"reply": "存了", "picks": [{"id": "b1", "why": "按你说的"}]})])),
               timeout=20)
print("SAVED ids", [i["id"] for i in saved["items"]], "actions", saved["actions"])
print("MARK", store.get_mark("b1"))

# TestModel 冒烟
try:
    smoke = rt.run(store, "随便", chain=[{"name": "stub", "model": "stub"}],
                   model=TestModel(call_tools=[], custom_output_text=None), timeout=20)
    print("SMOKE", smoke["engine"], smoke["count"])
except Exception as exc:
    print("SMOKE FAILED", type(exc).__name__, exc)

# 模型抛错 → 降级不崩
def boom(messages, info):
    raise RuntimeError("模型挂了")
err = rt.run(store, "找点东西", chain=[{"name": "stub", "model": "stub"}],
             model=FunctionModel(boom), timeout=20)
print("ERR", err["engine"], "|", err["reply"][:40], "| count", err["count"])
run2 = store.get_agent_run(err["run_id"])
print("ERR STATUS", run2["status"], [e["kind"] for e in run2["events"]])
store.close_all()
print("OK")
