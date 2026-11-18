import json, pathlib, sys, tempfile, time
sys.path.insert(0, r"E:\Documents\deepseek-harness\default-workspace\onefeed")
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from onefeed.store import Store
from onefeed import agent_runtime as rt

tmp = pathlib.Path(tempfile.mkdtemp())
store = Store(tmp / "t.db")
now = int(time.time())
store.upsert_items([{"id": "b1", "platform": "bilibili", "kind": "video", "title": "AI 编程实战", "published_at": now - 3600}])

def scripted(messages, info):
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"reply": "ok", "picks": []})])

res = rt.run(store, "找点 AI 的", chain=[{"name": "stub", "model": "stub"}],
             model=FunctionModel(scripted), timeout=20)
print(json.dumps({"error": res["error"], "run": store.get_agent_run(res["run_id"])["error"]}, ensure_ascii=True))
