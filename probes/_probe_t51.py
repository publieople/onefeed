import sys, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT / "tests"))
import test_agent_tasks as t
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from onefeed import agent_runtime as rt

store, db = t.fresh_store("probe")

def scripted(messages, info):
    returned = [p for m in messages for p in getattr(m, "parts", [])
                if isinstance(p, ToolReturnPart)]
    if not returned:
        return ModelResponse(parts=[ToolCallPart("summarize_batch", {"ids": ["bilibili:ai1", "bilibili:ai2"], "style": "brief"})])
    if len(returned) == 1:
        return ModelResponse(parts=[ToolCallPart("export_markdown", {"ids": ["bilibili:ai1", "bilibili:ai2"], "title": "AI 头条简报"})])
    name = info.output_tools[0].name if info.output_tools else "final_result"
    return ModelResponse(parts=[ToolCallPart(name, {"reply": "简报写好了", "picks": [{"id": "bilibili:ai1", "why": "x"}]})])

run = rt.run(store, "把这 2 条总结成简报存成 md", limit=4, model=FunctionModel(scripted), max_tools=5, timeout=30)
print(json.dumps({k: run[k] for k in ("engine", "steps", "ms", "error", "reply", "count")}, ensure_ascii=False))
print("actions", run["actions"])
print("files", [str(p) for p in (db.parent / "exports").glob("*.md")])
saved = store.get_agent_run(run["run_id"]) or {}
for e in saved.get("events") or []:
    print(e["seq"], e["kind"], e["name"], str(e.get("payload"))[:160])
