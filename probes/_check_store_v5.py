import os, sys, tempfile, time, pathlib
sys.path.insert(0, r"E:\Documents\deepseek-harness\default-workspace\onefeed")
tmp = pathlib.Path(tempfile.mkdtemp())
from onefeed.store import Store
s = Store(tmp / "t.db")
print("version", s.conn.execute("PRAGMA user_version").fetchone()[0])
now = int(time.time())
s.upsert_items([
  {"id": "b1", "platform": "bilibili", "kind": "video", "title": "AI 教程", "published_at": now - 60},
  {"id": "b2", "platform": "bilibili", "kind": "video", "title": "别的", "published_at": now - 120},
])
print("page", [r["id"] for r in s.page(limit=10)[0]])
s.mark_item("b2", hidden=True)
rows, _ = s.page(limit=10)
print("hidden filtered", [r["id"] for r in rows])
print("search", [r["id"] for r in s.search_items(terms=["AI"])])
s.mark_item("b1", saved=True)
print("saved", [r["id"] for r in s.saved_items()])
print("mark", s.get_mark("b1"))
s.start_agent_run("r1", "t1", "帮我找 AI", "minimax")
s.add_agent_step("r1", 1, "step", "think", {"title": "先搜一下"}, "")
s.add_agent_step("r1", 2, "action", "ui_filter", {"payload": {"platforms": ["bilibili"]}}, "")
s.finish_agent_run("r1", "done", "找到 1 条", steps=2, ms=1200, tokens=88)
run = s.get_agent_run("r1")
print("run", run["status"], run["reply"], run["steps"], len(run["events"]), run["events"][1]["name"])
print("recent", [(r["id"], r["status"]) for r in s.recent_agent_runs()])
print("undo read", s.mark_item("b1", read=True)["read"], s.mark_item("b1", read=False)["read"])
s.close_all()
print("OK")
