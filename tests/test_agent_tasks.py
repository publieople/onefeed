"""T51 验收：长任务动作（总结 / 批量总结 / 导出 Markdown + 撤销）。

跑法：python tests/test_agent_tasks.py [--verbose]

四件事必须成立：
1. 总结先读缓存；force=true 才重算；算完写回 summaries 表；
2. 批量总结有预算：没正文、库里没有、时间不够的都进 skipped，不假装成功；
3. 导出只在 <state>/exports 下写 md，撤销能删文件，越界 token 一律拒绝；
4. 模型真的能自己串起来：summarize_batch → export_markdown，事件流里有轨迹。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOME = ROOT / ".onefeed" / "tmp" / "tasks-test-home"
HOME.mkdir(parents=True, exist_ok=True)
for leftover in HOME.glob("settings.json"):
    leftover.unlink(missing_ok=True)
os.environ["ONEFEED_HOME"] = str(HOME)
os.environ.pop("ONEFEED_AI_KEY", None)
os.environ.pop("ONEFEED_AI_AGENT", None)

from fastapi.testclient import TestClient  # noqa: E402
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402

from onefeed import actions as act_mod  # noqa: E402
from onefeed import agent_runtime as rt  # noqa: E402
from onefeed import summary as summary_mod  # noqa: E402
from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0
NOW = int(time.time())


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def seed() -> list[dict]:
    rows = [
        ("bilibili:ai1", "bilibili", "video", "五分钟讲懂大模型推理", "AI 大模型 推理 讲清楚", 1, 300, 900),
        ("bilibili:ai2", "bilibili", "video", "本地部署 DeepSeek 实录", "显存 量化 部署 实录", 2, 1500, 200),
        ("xiaohongshu:ai1", "xiaohongshu", "images", "用 AI 做了一张海报", "海报 出图 分享", 1, 0, 60),
        ("bilibili:blank", "bilibili", "video", "这条没有正文", "", 3, 120, 10),
        ("zhihu:ai1", "zhihu", "article", "深度学习怎么找 idea", "科研 idea", 4, 0, 120),
        ("zhihu:ai2", "zhihu", "article", "第二条杂项", "杂项", 5, 0, 20),
    ]
    out = []
    for iid, platform, kind, title, text, hours, duration, like in rows:
        out.append({"id": iid, "platform": platform, "kind": kind, "title": title, "text": text,
                    "author": "作者", "cover": "", "url": "https://example.com/" + iid,
                    "published_at": NOW - hours * 3600, "duration": duration,
                    "like": like, "comment": 3, "share": 0, "view": 1000,
                    "tags": [], "extra": {}, "cluster_id": "", "fetched_at": NOW})
    return out


class Recorder:
    """接住 ctx.send 的三个参数 + undo token。"""

    def __init__(self):
        self.events: list[tuple[str, str, dict, str]] = []

    def __call__(self, kind: str, name: str, payload: dict, undo_token: str = "") -> None:
        self.events.append((kind, name, payload, undo_token))

    def token(self, name: str) -> str:
        for kind, act, payload, token in reversed(self.events):
            if kind == "action" and act == name:
                return token
        return ""


def fresh_store(name: str) -> Store:
    db = ROOT / ".onefeed" / "tmp" / f"tasks-test-{name}.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    store.upsert_items(seed())
    exports = db.parent / "exports"
    if exports.exists():
        for leftover in exports.glob("*.md"):
            leftover.unlink(missing_ok=True)
    return store, db


def main() -> int:
    orig_build = summary_mod.build

    # ---------------------------------------------------------------- 1) 注册表
    for name, level in (("summarize_item", "L0"), ("summarize_batch", "L0"),
                        ("export_markdown", "L2")):
        act = act_mod.REGISTRY.get(name)
        check(act is not None and act.level == level, f"{name} 已注册且级别 {level}")
    names = {a["name"] for a in act_mod.catalog()}
    check({"summarize_item", "summarize_batch", "export_markdown"} <= names, "catalog 能列出来")
    check("Markdown" in act_mod.REGISTRY["export_markdown"].summary, "动作说明可读")
    check("summarize_item" in rt.INSTRUCTIONS and "export_markdown" in rt.INSTRUCTIONS,
          "指令里教了模型怎么总结与导出")

    # ---------------------------------------------------------------- 2) 单条：缓存
    store, db = fresh_store("single")
    store.save_summary("bilibili:ai1", {"tldr": "已有结论", "points": [{"t": 30, "text": "要点一"}],
                                        "caveat": ""})
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("缓存命中时不该调用模型")

    summary_mod.build = boom
    try:
        rec = Recorder()
        ctx = act_mod.Ctx(store=store, emit=rec)
        out = act_mod.call(ctx, "summarize_item", {"id": "bilibili:ai1"})
        check(out["ok"] is True and out["cached"] is True, "有缓存时直接返回缓存")
        check(out["tldr"] == "已有结论", "缓存内容原样返回")
        check(out["points"][0]["t"] == 30, "时间点保留")
        check(calls["n"] == 0, "没有为了拿缓存去跑模型")
        check(rec.token("summarize_item") == "", "总结不需要撤销")
    finally:
        summary_mod.build = orig_build

    # ---------------------------------------------------------------- 3) 单条：force
    store.save_summary("bilibili:ai1", {"tldr": "旧结论", "points": [], "caveat": ""})
    built = {"tldr": "新结论", "points": [{"t": None, "text": "新要点"}], "caveat": "", "basis": "desc"}

    def fake_build(*_args, **_kwargs):
        return dict(built)

    summary_mod.build = fake_build
    try:
        ctx = act_mod.Ctx(store=store)
        out = act_mod.call(ctx, "summarize_item", {"id": "bilibili:ai1", "force": True})
        check(out["cached"] is False and out["tldr"] == "新结论", "force 时重算")
        cached = store.get_summary("bilibili:ai1")
        check(cached["payload"]["tldr"] == "新结论", "重算结果写回 summaries")
        out = act_mod.call(ctx, "summarize_item", {"id": "bilibili:ai1"})
        check(out["cached"] is True and out["tldr"] == "新结论", "重算之后走缓存")
    finally:
        summary_mod.build = orig_build

    missing_id = hidden = ""
    try:
        act_mod.call(act_mod.Ctx(store=store), "summarize_item", {"id": "ghost:1"})
    except act_mod.ActionError as exc:
        missing_id = str(exc)
    check("库里没有" in missing_id, "不存在的 id 给 ActionError，不抛栈")

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("这条内容没有能读的正文。")

    summary_mod.build = fail_build
    try:
        act_mod.call(act_mod.Ctx(store=store), "summarize_item", {"id": "bilibili:blank"})
    except act_mod.ActionError as exc:
        hidden = str(exc)
    check("没有能读的正文" in hidden, "没正文的条目转成 ActionError")
    summary_mod.build = orig_build

    # ---------------------------------------------------------------- 4) 批量
    def batch_build(_store, _host, row):
        if row["id"] == "bilibili:blank":
            raise RuntimeError("这条内容没有能读的正文。")
        return {"tldr": "批量：" + row["title"], "points": [{"t": None, "text": "要点"}], "caveat": ""}

    summary_mod.build = batch_build
    try:
        ctx = act_mod.Ctx(store=store)
        out = act_mod.call(ctx, "summarize_batch",
                           {"ids": ["bilibili:ai2", "bilibili:blank", "ghost:1"]})
        check(out["count"] == 1, "批量里成功的只有 1 条")
        check(len(out["skipped"]) == 2, "没正文 + 不存在都进 skipped")
        reasons = " ".join(s["error"] for s in out["skipped"])
        check("没有能读的正文" in reasons and "库里没有" in reasons, "skipped 带原因")
        check(out["summaries"][0]["tldr"].startswith("批量："), "成功条目带总结")
    finally:
        summary_mod.build = orig_build

    many = act_mod.call(act_mod.Ctx(store=store), "summarize_batch",
                        {"ids": [f"ghost:{i}" for i in range(8)]})
    check(len(many["skipped"]) == act_mod.BATCH_MAX, "批量按 6 条截断")

    # ---------------------------------------------------------------- 5) 导出 + 撤销
    store.save_summary("bilibili:ai1", {"tldr": "结论一", "points": [{"t": 12, "text": "要点甲"}],
                                        "caveat": ""})
    store.save_summary("bilibili:ai2", {"tldr": "结论二", "points": [{"t": None, "text": "要点乙"}],
                                        "caveat": ""})
    rec = Recorder()
    ctx = act_mod.Ctx(store=store, emit=rec)
    out = act_mod.call(ctx, "export_markdown",
                       {"ids": ["bilibili:ai1", "bilibili:ai2"], "title": "我的简报", "style": "outline"})
    path = Path(out["path"])
    exports = (db.parent / "exports").resolve()
    check(path.exists() and path.parent == exports, "md 写在 exports 目录里")
    check(path.suffix == ".md" and "我的简报" in path.name, "文件名带标题")
    text = path.read_text(encoding="utf-8")
    check("# 我的简报" in text, "文件有一级标题")
    check("## 1." in text and "五分钟讲懂大模型推理" in text, "每条有小标题")
    check("结论一" not in text, "outline 不写一句话结论")
    check("要点甲" in text and "[00:12]" in text, "要点与时间点都写进去了")
    check(out["count"] == 2 and out["bytes"] > 0, "返回条数与大小")

    token = rec.token("export_markdown")
    check(token != "" and json.loads(token)["kind"] == "export", "导出带撤销 token")
    undone = act_mod.apply_undo(store, token)
    check(undone["ok"] is True and not path.exists(), "撤销后文件被删掉")
    again = act_mod.apply_undo(store, token)
    check(again["ok"] is True and "已经不在" in again["note"], "重复撤销不报错")

    # ---------------------------------------------------------------- 6) 撤销越界
    outside = db.parent / "evil.md"
    outside.write_text("别删我", encoding="utf-8")
    bad = act_mod.apply_undo(store, json.dumps({"kind": "export", "path": str(outside)}))
    check(bad["ok"] is False and outside.exists(), "exports 外的文件不删")
    txt = exports / "looks.txt"
    txt.write_text("x", encoding="utf-8")
    bad = act_mod.apply_undo(store, json.dumps({"kind": "export", "path": str(txt)}))
    check(bad["ok"] is False and txt.exists(), "只撤销 md")
    nested = exports / "sub"
    nested.mkdir(exist_ok=True)
    inner = nested / "x.md"
    inner.write_text("x", encoding="utf-8")
    bad = act_mod.apply_undo(store, json.dumps({"kind": "export", "path": str(inner)}))
    check(bad["ok"] is False and inner.exists(), "子目录里的文件不删")
    outside.unlink(missing_ok=True)
    txt.unlink(missing_ok=True)
    inner.unlink(missing_ok=True)

    # ---------------------------------------------------------------- 7) 模型自己串起来
    store2, db2 = fresh_store("run")

    def scripted(messages, info):
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart(
                "summarize_batch", {"ids": ["bilibili:ai1", "bilibili:ai2"], "style": "brief"})])
        if len(returned) == 1:
            return ModelResponse(parts=[ToolCallPart(
                "export_markdown",
                {"ids": ["bilibili:ai1", "bilibili:ai2"], "title": "AI 头条简报"})])
        name = info.output_tools[0].name if info.output_tools else "final_result"
        return ModelResponse(parts=[ToolCallPart(name, {
            "reply": "简报写好了，看 exports 目录。",
            "picks": [{"id": "bilibili:ai1", "why": "第一条"}]})])

    summary_mod.build = orig_build
    run = rt.run(store2, "把这 2 条总结成简报存成 md", limit=4,
                 model=FunctionModel(scripted), max_tools=5, timeout=30)
    check(run["engine"] == "agent" and run["steps"] == 2, "模型两步走完（批量总结 → 导出）")
    check(any(a["name"] == "export_markdown" for a in run["actions"]), "done.actions 里有导出")
    files = list((db2.parent / "exports").glob("*.md"))
    check(len(files) == 1, "真跑出了一个 md 文件")
    body = files[0].read_text(encoding="utf-8")
    check("# AI 头条简报" in body and "## 2." in body, "文件内容来自真实动作")
    check(run["reply"] == "简报写好了，看 exports 目录。", "回复原样保留")
    saved = store2.get_agent_run(run["run_id"]) or {}
    steps = saved.get("events") or []
    titles = [str((s.get("data") or {}).get("title", "")) for s in steps]
    check(any("批量总结" in t for t in titles) and any("导出 md" in t for t in titles),
          "轨迹里能看到两步的标题")
    for f in files:
        f.unlink(missing_ok=True)

    # ---------------------------------------------------------------- 8) API 撤销
    store3, _db3 = fresh_store("api")
    target = _db3.parent / "exports" / "20260101-000000-api.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# api", encoding="utf-8")
    client = TestClient(create_app(store3))
    resp = client.post("/api/agent/undo", json={"token": json.dumps(
        {"kind": "export", "path": str(target)})})
    check(resp.status_code == 200 and resp.json()["ok"] is True, "HTTP 撤销导出成功")
    check(not target.exists(), "文件确实删了")
    resp = client.post("/api/agent/undo", json={})
    check(resp.status_code == 400, "缺 token 时 400")

    # ---------------------------------------------------------------- 9) 活动列表
    thread = "th-activity"
    rid = "run-activity"
    store3.start_agent_run(rid, thread, "把这 2 条导出成 md", model="fake")
    store3.add_agent_step(rid, 1, "step", "导出 md「活动」", {"args": {}})
    store3.add_agent_step(rid, 2, "action", "export_markdown",
                          {"path": str(target), "count": 2},
                          undo_token=json.dumps({"kind": "export", "path": str(target)}))
    store3.add_agent_step(rid, 3, "done", "", {"reply": "写好了"})
    store3.finish_agent_run(rid, status="done", reply="写好了", steps=2, ms=1200, tokens=99)

    plain = store3.recent_agent_runs(limit=5)
    check(len(plain) == 1 and "events" not in plain[0], "默认不带事件流水")
    rich = store3.recent_agent_runs(limit=5, steps=True)
    check(len(rich[0]["events"]) == 3, "steps=True 带出三条事件")
    acts = [e for e in rich[0]["events"] if e["kind"] == "action" and e["undo_token"]]
    check(len(acts) == 1 and acts[0]["name"] == "export_markdown", "动作事件带 undo_token")
    check(acts[0]["data"]["count"] == 2, "事件内容从 data 读")

    listing = client.get("/api/agent/runs", params={"events": 1})
    body = listing.json()
    check(listing.status_code == 200 and body["runs"][0]["status"] == "done", "活动列表返回这一轮")
    check(len(body["runs"][0].get("events") or []) == 3, "?events=1 带回事件")
    plain_body = client.get("/api/agent/runs").json()
    check("events" not in plain_body["runs"][0], "不带参数就不塞事件")

    for s in (store, store2, store3):
        s.close_all()
    print(f"✅ test_agent_tasks.py  T51 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
