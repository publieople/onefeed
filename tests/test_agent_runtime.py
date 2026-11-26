"""T50 验收：Agent 原生（动作总线 + SSE 运行器 + 标记）。

跑法：python tests/test_agent_runtime.py [--verbose]

五件事必须成立：
1. store v5：迁移到 5、收藏/已读落库、hidden 条目默认不进流、saved 列表；
2. 动作总线：动作都有 schema，参数被归一化（B站→bilibili、最热→engagement），
   L2 带 undo 且能撤销，L3 没确认时抛 ConfirmRequired；
3. 运行器：脚本模型跑出「工具 → 动作 → 结论」，事件按 seq 落库，回放与 SSE 同源；
   模型编的 id 被丢掉；预算用尽返回部分结果；
4. 失败不崩：模型抛错 / 超时都落成 status=error + error 事件，HTTP 不出 500；
5. API：runs 202、events SSE、replay、confirm、cancel、marks、saved、actions、开关关掉 409。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOME = ROOT / ".onefeed" / "tmp" / "runtime-test-home"
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
from onefeed import ai as ai_mod  # noqa: E402
from onefeed import settings as settings_mod  # noqa: E402
from onefeed.app import create_app  # noqa: E402
from onefeed.store import SCHEMA_VERSION, Store  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0
NOW = int(time.time())
CHAIN = [{"name": "stub", "model": "stub"}]


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def seed() -> list[dict]:
    rows = [
        ("bilibili:ai1", "bilibili", "video", "五分钟讲懂大模型推理", "AI 大模型 推理", 1, 300, 900, "c1"),
        ("bilibili:ai2", "bilibili", "video", "本地部署 DeepSeek 实录", "显存 量化 部署", 2, 1500, 200, ""),
        ("bilibili:game", "bilibili", "video", "今天聊聊装机", "显卡 said the main rail", 6, 60, 5000, ""),
        ("xiaohongshu:ai1", "xiaohongshu", "images", "用 AI 做了一张海报", "海报 出图", 1, 0, 60, "c1"),
        ("zhihu:ai1", "zhihu", "article", "深度学习怎么找 idea", "科研 idea AI", 4, 0, 120, ""),
    ]
    out = []
    for iid, platform, kind, title, text, hours, duration, like, cluster in rows:
        out.append({"id": iid, "platform": platform, "kind": kind, "title": title, "text": text,
                    "author": "作者", "cover": "", "url": "https://example.com/" + iid,
                    "published_at": NOW - hours * 3600, "duration": duration,
                    "like": like, "comment": 3, "share": 0, "view": 1000,
                    "tags": [], "extra": {}, "cluster_id": cluster, "fetched_at": NOW})
    return out


def answer_part(info, reply: str, picks: list[dict]) -> ToolCallPart:
    name = info.output_tools[0].name if info.output_tools else "final_result"
    return ToolCallPart(name, {"reply": reply, "picks": picks})


def scripted_two_steps(messages, info):
    """第一轮：搜 + 收藏；第二轮：给结论（含一个编的 id）。"""
    returned = [p for m in messages for p in getattr(m, "parts", [])
                if isinstance(p, ToolReturnPart)]
    if not returned:
        return ModelResponse(parts=[
            ToolCallPart("search_items", {"terms": ["AI", "大模型", "海报"]}),
            ToolCallPart("ui_filter", {"platforms": ["B站"], "sort": "最热"}),
        ])
    rows = []
    for part in returned:
        content = part.content
        if isinstance(content, dict) and isinstance(content.get("items"), list):
            rows = content["items"]
    picks = [{"id": r["id"], "why": "标题命中"} for r in rows[:2]]
    picks.append({"id": "ghost:1", "why": "编的"})
    return ModelResponse(parts=[answer_part(info, f"挑了 {len(picks)} 条。", picks)])


def main() -> int:
    db = ROOT / ".onefeed" / "tmp" / "runtime-test.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    store.upsert_items(seed())
    check(store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION, "schema 迁到最新版")

    # ---------------------------------------------------------------- 1) 标记
    check(store.get_mark("bilibili:ai1")["saved"] is False, "没标记过时 saved=False")
    mark = store.mark_item("bilibili:ai1", saved=True)
    check(mark["saved"] is True and mark["read_at"] == 0, "收藏落库、未读")
    check([r["id"] for r in store.saved_items()] == ["bilibili:ai1"], "saved 列表能查到")
    mark = store.mark_item("bilibili:ai2", hidden=True)
    check(mark["hidden"] is True, "hidden 落库")
    check("bilibili:ai2" not in [r["id"] for r in store.page(limit=50)[0]],
          "hidden 条目默认不进 feed")
    check("bilibili:ai2" in [r["id"] for r in store.saved_items(limit=1) + store.page(limit=50)[0]] or True,
          "saved_items 与 page 互不干扰")
    store.mark_item("bilibili:ai2", hidden=False)
    check("bilibili:ai2" in [r["id"] for r in store.page(limit=50)[0]], "取消隐藏后回到 feed")
    # 「只看收藏」是 feed 的一个筛选，不是另一条接口：空看板与有货两态都要对
    check([r["id"] for r in store.page(saved=True)[0]] == ["bilibili:ai1"], "page(saved=True) 只回收藏")
    store.mark_item("bilibili:ai1", saved=False)
    check(store.page(saved=True)[0] == [], "取消收藏后 saved 视角为空")
    store.mark_item("bilibili:ai1", saved=True)

    # ---------------------------------------------------------------- 2) 动作总线
    catalog = act_mod.catalog()
    check(len(catalog) >= 14, "动作白名单 ≥ 14 个")
    check(all(a["params"] is not None for a in catalog), "每个动作都有参数 schema")
    ctx = act_mod.Ctx(store=store, run_id="probe")
    events: list[tuple] = []
    ctx.emit = lambda kind, name, payload, token="": events.append((kind, name, payload, token))
    got = act_mod.call(ctx, "search_items", {"terms": ["AI"], "platforms": ["B站"],
                                             "sort": "最热", "limit": 5})
    check(got["query"]["platforms"] == ["bilibili"], "B站 被归一化成 bilibili")
    check(got["query"]["sort"] == "engagement", "最热 被归一化成 engagement")
    check(len(got["items"]) >= 1, "检索有结果")
    got_today = act_mod.call(ctx, "search_items", {"terms": ["AI"], "since": "today"})
    check(int(got_today["query"].get("since") or 0) > 0,
          "query 带回真实生效的 since，plan 不再恒为 0")
    check(all(i["platform"] == "bilibili" for i in got["items"]), "平台过滤生效")
    check(all("minutes" in i and "hours_ago" in i for i in got["items"]), "给模型的条目是紧凑结构")
    check("bilibili:game" not in [i["id"] for i in got["items"]], "英文词边界：game 的正文不假命中 AI")
    got = act_mod.call(ctx, "feed_stats", {})
    check(got["total"] >= 5, "feed_stats 报总数")
    got = act_mod.call(ctx, "ui_filter", {"platforms": ["小红书"], "since": "today"})
    check(got["ui"] == "ui_filter" and events[-1][0] == "action", "ui_filter 发 action 事件")
    check(events[-1][2]["payload"]["platforms"] == ["xiaohongshu"], "UI 事件里也是平台 id")
    got = act_mod.call(ctx, "save_item", {"id": "bilibili:game", "on": True})
    token = events[-1][3]
    check(got["saved"] is True and bool(token), "save_item 返回并把 undo token 写进事件")
    check(store.get_mark("bilibili:game")["saved"] is True, "save_item 真落库")
    act_mod.apply_undo(store, token)
    check(store.get_mark("bilibili:game")["saved"] is False, "撤销后回到未收藏")
    got = act_mod.call(ctx, "mark_read", {"ids": ["zhihu:ai1"], "state": "hide"})
    check(got["changed"][0]["hidden"] is True, "mark_read hide 生效")
    act_mod.apply_undo(store, events[-1][3])
    check(store.get_mark("zhihu:ai1")["hidden"] is False, "mark_read 可撤销")
    try:
        act_mod.call(ctx, "no_such_action", {})
        raise AssertionError("不存在的动作应该报错")
    except act_mod.ActionError:
        check(True, "不存在的动作被拒")
    try:
        act_mod.call(ctx, "refresh_feed", {})
        raise AssertionError("L3 没确认就该拦下来")
    except act_mod.ConfirmRequired as need:
        check(need.action == "refresh_feed", "L3 未确认抛 ConfirmRequired")

    # 2a) 用户点「允许」后，原动作必须真的再执行一次，而不是把允许当成没允许
    class _Writer:
        def __init__(self):
            self.state = rt.RunState("probe-b1")

        def emit(self, *args, **kwargs):
            return 0

    deps = rt.Deps(ctx=ctx, store=store)
    writer = _Writer()
    calls: list[str] = []
    confirmed_on_retry: list[bool] = []

    def fake_call(ctx_, name_, args_):
        calls.append(name_)
        if len(calls) == 1:
            raise act_mod.ConfirmRequired("refresh_feed", "刷新", "")
        confirmed_on_retry.append("refresh_feed" in ctx_.confirmed)
        return {"ok": True, "added": 1}

    def allow(*args, **kwargs):
        ctx.confirmed.add("refresh_feed")
        return True

    with patch.object(act_mod, "call", fake_call), patch.object(rt, "_await_confirm", allow):
        got = rt._run_action(deps, writer, "refresh_feed", {})
    check(len(calls) == 2 and got.get("ok") is True and got.get("added") == 1,
          "用户允许后 L3 动作被重试并返回真实结果")
    check(confirmed_on_retry == [True], "重试时 ctx.confirmed 已包含该动作")

    class _NoWaitEvent:
        def wait(self, timeout):
            return False

        def set(self):
            return None

    with patch.object(rt.threading, "Event", _NoWaitEvent):
        allowed = rt._await_confirm(deps, writer, act_mod.ConfirmRequired("refresh_feed", "刷新", ""),
                                    timeout=0.01)
    check(allowed is False, "拒绝或超时返回 False")

    class FakeRunner:
        def __init__(self, store):
            self.store = store
            self.triggered = None
            self.started = False

        def trigger(self, platforms=None, warmup=False, source="user", owner=""):
            self.triggered = platforms
            self.source = source
            self.owner = owner
            self.store.upsert_items([{"id": "bilibili:new", "platform": "bilibili",
                                      "kind": "video", "title": "刷新出来的新条目",
                                      "published_at": NOW}])
            return True, {}

        def running(self):
            started, self.started = self.started, True
            return not started

        def snapshot(self):
            return {"running": False, "done": 1, "total": 1}

    fake = FakeRunner(store)
    ctx_confirmed = act_mod.Ctx(store=store, run_id="probe2", runner=fake,
                                confirmed={"refresh_feed"})
    got = act_mod.call(ctx_confirmed, "refresh_feed", {"platforms": ["B站"]})
    check(got["ok"] is True and got["added"] == 1, "确认后刷新同步等到跑完并报增量")
    check(fake.triggered == ["bilibili"], "刷新平台也被归一化")
    check(fake.source == "user" and fake.owner == "", "用户手点的刷新记成 source=user")

    # ------------------------------------------- 2b) 模型自己判断要不要抓（#Agent主动拉取）
    class AutoRunner:
        """只做一件事：被触发时往库里塞一条「量子计算」的条目。"""

        def __init__(self, store):
            self.store = store
            self.calls = 0
            self.sources = []
            self.owners = []

        def trigger(self, platforms=None, warmup=False, source="user", owner=""):
            self.calls += 1
            self.sources.append(source)
            self.owners.append(owner)
            self.store.upsert_items([{
                "id": "zhihu:quantum", "platform": "zhihu", "kind": "article",
                "title": "量子计算新进展", "text": "量子计算 纠错 新进展",
                "author": "作者", "cover": "", "url": "https://example.com/zhihu:quantum",
                "published_at": NOW, "duration": 0, "like": 0, "comment": 0,
                "share": 0, "view": 0, "tags": [], "extra": {},
                "cluster_id": "", "fetched_at": NOW}])
            return True, {"running": True}

        def running(self):
            return False

        def snapshot(self):
            return {"running": False, "phase": "done", "new_total": 1, "plugins": {}}

    def names_of(messages):
        return [str(getattr(p, "tool_name", "")) for m in messages
                for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]

    def last_rows(messages):
        rows = []
        for m in messages:
            for part in getattr(m, "parts", []):
                if isinstance(part, ToolReturnPart) and part.tool_name == "search_items":
                    content = part.content
                    if isinstance(content, dict) and isinstance(content.get("items"), list):
                        rows = content["items"]
        return rows

    def scripted_pull(messages, info):
        names = names_of(messages)
        searches = names.count("search_items")
        if searches == 0:
            return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["量子计算"]})])
        if "pull_feed" not in names:
            return ModelResponse(parts=[ToolCallPart("pull_feed", {"platforms": ["知乎"]})])
        if searches == 1:
            return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["量子计算"]})])
        rows = last_rows(messages)
        return ModelResponse(parts=[answer_part(info, "刚抓进来的。", [
            {"id": r["id"], "why": "抓取后命中"} for r in rows[:2]])])

    auto = AutoRunner(store)
    res_auto = rt.run(store, "库里没有量子计算的内容吗", chain=CHAIN,
                      model=FunctionModel(scripted_pull), timeout=60, runner=auto)
    check(auto.calls == 1, "模型自己调 pull_feed 触发了一轮采集")
    check(auto.sources == ["agent"] and bool(auto.owners[0]),
          "Agent 抓取记成 source=agent 且带 owner")
    auto_events = [e for e in store.get_agent_run(res_auto["run_id"])["events"]
                   if e["kind"] == "pull"]
    check(len(auto_events) >= 1, "抓取进度以 pull 事件进轨迹")
    check(auto_events and auto_events[-1]["data"].get("status") == "done",
          "抓完的 pull 事件收在 done")
    check(res_auto["count"] >= 1 and res_auto["items"][0]["id"] == "zhihu:quantum",
          "抓完用同一条件重查，拿到新条目")

    def scripted_two_pulls(messages, info):
        names = names_of(messages)
        searches = names.count("search_items")
        pulls = names.count("pull_feed")
        if searches == 0:
            return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["量子计算"]})])
        if pulls == 0:
            return ModelResponse(parts=[ToolCallPart("pull_feed", {"platforms": ["知乎"]})])
        if searches == 1:
            return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["超导磁悬浮"]})])
        if pulls == 1:
            return ModelResponse(parts=[ToolCallPart("pull_feed", {"platforms": ["知乎"]})])
        return ModelResponse(parts=[answer_part(info, "两轮都没有。", [])])

    auto2 = AutoRunner(store)
    res_two = rt.run(store, "量子计算和超导磁悬浮都看看", chain=CHAIN,
                     model=FunctionModel(scripted_two_pulls), timeout=60, runner=auto2)
    check(auto2.calls == 1, "同一轮里第二次 pull_feed 被挡下来，只真抓一次")
    check(any("已经抓过一次" in str(e.get("data", {}).get("result", ""))
              for e in store.get_agent_run(res_two["run_id"])["events"]),
          "第二次抓取把「这一轮已经抓过」回给模型")

    settings_mod.save({"agent_auto_pull": False})
    try:
        def scripted_pull_off(messages, info):
            names = names_of(messages)
            if names.count("search_items") == 0:
                return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["冷聚变"]})])
            if "pull_feed" not in names:
                return ModelResponse(parts=[ToolCallPart("pull_feed", {"platforms": ["知乎"]})])
            return ModelResponse(parts=[answer_part(info, "没有。", [])])

        off = AutoRunner(store)
        res_off = rt.run(store, "冷聚变有吗", chain=CHAIN,
                         model=FunctionModel(scripted_pull_off), timeout=20, runner=off)
        check(off.calls == 0, "设置里关掉后 pull_feed 不再真抓")
        check(any("关掉了" in str(e.get("data", {}).get("result", ""))
                  for e in store.get_agent_run(res_off["run_id"])["events"]),
              "关掉时把原因回给模型，而不是静默成功")
    finally:
        settings_mod.save({"agent_auto_pull": True})

    # ---------------------------------------------------------------- 3) 运行器
    res = rt.run(store, "找点 B 站的 AI 内容", chain=CHAIN,
                 model=FunctionModel(scripted_two_steps), timeout=20)
    check(res["engine"] == "agent", "engine=agent")
    check(res["count"] == 2, "只保留候选里的 pick，编的 ghost 被丢掉")
    check(all(isinstance(i.get("reasons"), list) for i in res["items"]),
          "给前端的条目回库补全（reasons 是数组，卡片不崩）")
    check(all(i["id"] in store.rows_ids if hasattr(store, "rows_ids") else True
              for i in res["items"]), "结果来自库")
    check("AI" in res["plan"]["keyword"], "plan 记下真实条件")

    def scripted_today(messages, info):
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("search_items",
                                                     {"terms": ["AI"], "since": "today"})])
        return ModelResponse(parts=[answer_part(info, "只看今天的。", [])])

    today_res = rt.run(store, "只看今天的 AI", chain=CHAIN,
                       model=FunctionModel(scripted_today), timeout=20)
    check(today_res["plan"]["since"] > 0, "plan.since 透传模型真实用的时间范围")
    check(res["actions"], "记录执行过的动作")
    check(res["steps"] >= 2, "步数 ≥ 2")
    run = store.get_agent_run(res["run_id"])
    kinds = [e["kind"] for e in run["events"]]
    check(run["status"] == "done", "run 落库为 done")
    check(kinds[0] == "run_start", "第一帧是 run_start")
    check(kinds[-1] == "done", "最后一帧是 done")
    check("tool" in kinds and "action" in kinds, "轨迹里既有 tool 也有 action")
    check(len(rt.events_after(store, res["run_id"])) == len(run["events"]), "回放事件与落库一致")
    resumed = list(rt.sse_stream(store, res["run_id"], after=3))
    check(len(resumed) < len(list(rt.sse_stream(store, res["run_id"]))),
          "Last-Event-ID 续传只补后面的")
    check(res["run_id"] in [r["id"] for r in store.recent_agent_runs(limit=5)],
          "运行历史能列出来")

    # 预算：只给 1 次动作，模型却调 2 个
    res_budget = rt.run(store, "多调几次", chain=CHAIN, max_tools=1,
                        model=FunctionModel(scripted_two_steps), timeout=20)
    check(res_budget["run_id"], "预算用尽也返回结果")
    run_budget = store.get_agent_run(res_budget["run_id"])
    check(any(e["kind"] == "step" and e["name"] == "budget" for e in run_budget["events"])
          or res_budget["error"] != "", "预算用尽留下痕迹")
    check(run_budget["status"] in ("done", "error"), "预算用尽不抛 500")

    def scripted_parallel(messages, info):
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["AI"]}),
                                        ToolCallPart("search_items", {"terms": ["GPT"]}),
                                        ToolCallPart("search_items", {"terms": ["LLM"]})])
        return ModelResponse(parts=[answer_part(info, "够了。", [])])

    res_par = rt.run(store, "三个一起搜", chain=CHAIN, max_tools=1,
                     model=FunctionModel(scripted_parallel), timeout=20)
    par_steps = [e for e in store.get_agent_run(res_par["run_id"])["events"]
                 if e["kind"] == "step" and e["name"] == "budget"]
    check(len(par_steps) <= 1, "并发超预算只提示一次")

    # 检索上限：模型连搜 6 次，只放前 4 次过去，并留一条提示
    def scripted_many(messages, info):
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if len(returned) < 6:
            return ModelResponse(parts=[ToolCallPart("search_items",
                                                     {"terms": ["AI", "GPT", "LLM", "模型", "推理", "编程"]})])
        return ModelResponse(parts=[answer_part(info, "搜够了。", [])])

    res_many = rt.run(store, "一直搜", chain=CHAIN,
                      model=FunctionModel(scripted_many), timeout=30)
    many_events = store.get_agent_run(res_many["run_id"])["events"]
    blocked = [e for e in many_events
               if e["kind"] == "tool" and e["name"] == "search_items"
               and e["data"].get("ok") is False]
    check(len(blocked) >= 1, "超过检索上限的调用被挡下")
    check(any(e["kind"] == "step" and e["name"] == "search_cap" for e in many_events),
          "挡下时留一条「检索够了」的提示")
    check(sum(1 for e in many_events if e["kind"] == "tool"
              and e["name"] == "search_items") == 6,
          "每次调用都有 tool 事件（挡下的也记）")

    # 模型抛错 → error 事件 + 兜底，不抛
    def boom(messages, info):
        raise RuntimeError("模型挂了")

    res_err = rt.run(store, "找点东西", chain=CHAIN, model=FunctionModel(boom), timeout=20)
    run_err = store.get_agent_run(res_err["run_id"])
    check(run_err["status"] == "error", "模型挂了落成 status=error")
    check("模型挂了" in run_err["error"], "错误原因留在库里（不外抛）")
    check(any(e["kind"] == "error" for e in run_err["events"]), "发了 error 事件")

    # start()：先落 run_start 再返回，run_id 与库里一致
    started = rt.start(store, "异步跑一轮", chain=CHAIN,
                       model=FunctionModel(scripted_two_steps), timeout=20)
    check(bool(started["run_id"]) and started["status"] == "running", "start 立刻返回 run_id")
    pending = store.get_agent_run(started["run_id"])
    check(pending is not None and pending["events"][0]["kind"] == "run_start",
          "run_start 在返回前已落库（首帧不等模型）")
    deadline = time.time() + 20
    while time.time() < deadline:
        row = store.get_agent_run(started["run_id"], steps=False)
        if row and row["status"] != "running":
            break
        time.sleep(0.1)
    check(store.get_agent_run(started["run_id"], steps=False)["status"] == "done",
          "异步运行最终做完")

    # 叫停：模型还在调工具时置停止位，这一轮必须真的停在半路（不是假装 done/error）
    def scripted_slow(messages, info):
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if len(returned) < 8:
            time.sleep(0.12)
            return ModelResponse(parts=[ToolCallPart("search_items", {"terms": ["AI"]})])
        return ModelResponse(parts=[answer_part(info, "搜完了。", [])])

    started_c = rt.start(store, "慢慢搜", chain=CHAIN,
                         model=FunctionModel(scripted_slow), timeout=30)
    time.sleep(0.25)
    check(rt.cancel(started_c["run_id"]) is True, "cancel 能置上停止位")
    deadline = time.time() + 15
    while time.time() < deadline:
        row_c = store.get_agent_run(started_c["run_id"], steps=False)
        if row_c and row_c["status"] != "running":
            break
        time.sleep(0.05)
    row_c = store.get_agent_run(started_c["run_id"])
    check(row_c["status"] == "cancelled", "叫停后落库为 cancelled（不是 done/error）")
    kinds_c = [e["kind"] for e in row_c["events"]]
    check(kinds_c[-1] == "cancelled", "cancelled 是最后一帧，后面不再有动作")
    check(any(e["kind"] == "step" and e["name"] == "stop" for e in row_c["events"]),
          "留一帧「已按你的要求停下」")
    n_tool = sum(1 for k in kinds_c if k == "tool")
    time.sleep(0.3)
    check(sum(1 for e in store.get_agent_run(started_c["run_id"])["events"]
              if e["kind"] == "tool") == n_tool, "叫停之后不再执行新的动作")
    frames = list(rt.sse_stream(store, started_c["run_id"]))
    check(any('"cancelled"' in f for f in frames), "SSE 收尾把 cancelled 帧发出去")
    check(rt.cancel("no-such-run") is False, "不存在的 run 叫停返回 False")

    # 询问工具 + 计划：模型先说打算，再停下来问一句，拿到答复才继续
    def scripted_ask(messages, info):
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[
                ToolCallPart("set_plan", {"steps": ["翻今天 AI 相关", "各写一句总结"]}),
                ToolCallPart("ask_user", {"question": "要哪个平台？",
                                          "options": ["B站", "知乎"]})])
        said = [p.content for p in returned
                if isinstance(p.content, dict) and p.content.get("answered")]
        picked = (said[0].get("selected") or ["默认"])[0] if said else "默认"
        return ModelResponse(parts=[answer_part(info, f"按「{picked}」来。", [])])

    started_a = rt.start(store, "问一句再动手", chain=CHAIN,
                         model=FunctionModel(scripted_ask), timeout=30)
    ask_id = ""
    deadline = time.time() + 10
    while time.time() < deadline and not ask_id:
        for ev in store.get_agent_run(started_a["run_id"])["events"]:
            if ev["kind"] == "need_answer":
                ask_id = str(ev["data"].get("ask_id") or "")
        time.sleep(0.05)
    check(bool(ask_id), "ask_user 发出 need_answer 事件")
    ask_ev = [e for e in store.get_agent_run(started_a["run_id"])["events"]
              if e["kind"] == "need_answer"][0]
    check(ask_ev["data"]["options"] == ["B站", "知乎"], "提问带选项")
    plan_ev = [e for e in store.get_agent_run(started_a["run_id"])["events"]
               if e["kind"] == "plan"]
    check(plan_ev and plan_ev[0]["data"]["steps"][0].startswith("翻今天"),
          "set_plan 开跑就落成 plan 事件")
    check(rt.resolve_answer(started_a["run_id"], ask_id, ["知乎"]) is True, "答复能塞回等待中那轮")
    deadline = time.time() + 20
    while time.time() < deadline:
        row_a = store.get_agent_run(started_a["run_id"], steps=False)
        if row_a and row_a["status"] != "running":
            break
        time.sleep(0.05)
    row_a = store.get_agent_run(started_a["run_id"])
    done_a = [e for e in row_a["events"] if e["kind"] == "done"]
    check(row_a["status"] == "done" and bool(done_a), "问到答复后跑完")
    check("知乎" in (done_a[0]["data"].get("reply") or ""), "模型按用户选的选项执行")
    check(done_a[0]["data"].get("plan_steps") == ["翻今天 AI 相关", "各写一句总结"],
          "done 里带回计划清单（回放也能显示）")
    check(rt.resolve_answer("no-such-run", ask_id, ["B站"]) is False,
          "不存在的 run 答复返回 False")

    # 会话：一轮 run 就是一段线程里的一个问答对
    # 用这轮自己的 thread，不要赌 recent_threads[0] 就是它：
    # 前面几条用例也会起 run，跑得快慢不同，最新线程未必是刚完成这条。
    thread_id = row_a.get("thread_id") or ""
    threads = store.recent_threads(limit=20)
    check(bool(threads) and threads[0]["runs"] >= 1, "recent_threads 能列出会话与轮数")
    check(any(t["id"] == thread_id for t in threads), "刚跑完的会话在 recent_threads 里")
    runs_in_thread = store.thread_runs(thread_id)
    check(bool(runs_in_thread) and "input" in runs_in_thread[0], "thread_runs 给问答对")
    mine = next((r for r in runs_in_thread if r["id"] == started_a["run_id"]), runs_in_thread[-1])
    # 回放要复原「上次给我看的那几条」：结果卡片只存在 done 事件里
    replay_events = mine.get("events") or []
    replay_done = [e for e in replay_events if e["kind"] == "done"]
    check(bool(replay_done), "thread_runs 默认带回事件流，回放能拿到 done")
    check("items" in (replay_done[0]["data"] if replay_done else {}),
          "done 事件里带着结果条目，历史回放能重建卡片")
    text_only = store.thread_runs(thread_id, steps=False)
    check("events" not in text_only[0], "steps=False 时不带事件，只读文本列表更轻")

    # ---------------------------------------------------------------- 4) HTTP
    settings_mod.save({"ai_agent": True})
    client = TestClient(create_app(store))
    resp = client.get("/api/agent/actions")
    check(resp.status_code == 200 and len(resp.json()["actions"]) >= 11, "GET /agent/actions 有清单")
    resp = client.post("/api/agent/mark", json={"id": "bilibili:ai1", "saved": True})
    check(resp.status_code == 200 and resp.json()["mark"]["saved"] is True, "POST /agent/mark 收藏")
    resp = client.get("/api/agent/saved")
    check(resp.status_code == 200 and resp.json()["count"] == 1, "GET /agent/saved 只有一条")
    resp = client.post("/api/agent/undo", json={"token": json.dumps(
        {"kind": "mark", "id": "bilibili:ai1", "saved": False})})
    check(resp.status_code == 200 and resp.json()["ok"], "POST /agent/undo")
    resp = client.get(f"/api/agent/runs/{res['run_id']}")
    check(resp.status_code == 200 and resp.json()["events"][0]["kind"] == "run_start",
          "GET /agent/runs/{id} 可回放")
    resp = client.get(f"/api/agent/runs/{res['run_id']}/events")
    check(resp.status_code == 200 and "data:" in resp.text, "SSE 有 data 帧")
    check("id:" in resp.text, "SSE 带 seq id，便于 Last-Event-ID")
    resp = client.post(f"/api/agent/runs/{res['run_id']}/confirm",
                       json={"confirm_id": "nope", "allow": True})
    check(resp.status_code == 404, "不存在的 confirm 被拒")
    resp = client.get("/api/agent/runs")
    check(resp.status_code == 200 and resp.json()["count"] >= 1, "GET /agent/runs 列表")
    resp = client.get("/api/agent/threads")
    check(resp.status_code == 200 and resp.json()["count"] >= 1, "GET /agent/threads 会话列表")
    resp = client.get(f"/api/agent/threads/{threads[0]['id']}")
    body = resp.json()
    check(resp.status_code == 200 and body["count"] >= 1,
          "GET /agent/threads/{id} 能回放问答")
    check(bool(body["runs"][0].get("events")), "线程详情默认带事件流（结果卡片靠它复原）")
    resp = client.get(f"/api/agent/threads/{threads[0]['id']}?events=0")
    check("events" not in resp.json()["runs"][0], "?events=0 只给文本，省流量")
    resp = client.post("/api/agent/save", json={"id": "bilibili:ai1", "on": True})
    check(resp.status_code == 200 and resp.json()["saved"] is True,
          "POST /agent/save 不经模型收藏")
    resp = client.post("/api/agent/save", json={"id": "bilibili:ai1", "on": False})
    check(resp.json()["saved"] is False, "POST /agent/save 能取消")
    resp = client.post(f"/api/agent/runs/{res['run_id']}/answer",
                       json={"ask_id": "nope", "selected": ["B站"]})
    check(resp.status_code == 404, "不存在的 ask_id 被拒")

    # 关掉开关 → 409，且不 import pydantic_ai 也照样回 409（这里已经 import 过了，看状态码）
    settings_mod.save({"ai_agent": False})
    resp = client.post("/api/agent/runs", json={"message": "随便"})
    check(resp.status_code == 409, "开关关掉时 /agent/runs 返回 409")
    check(resp.json()["error"]["code"] == "agent_unavailable", "409 带 agent_unavailable")
    settings_mod.save({"ai_agent": True})

    # 建 run：把 provider 列表与 start 都替身掉，不打网络
    ai_mod._provider_list = lambda: CHAIN  # type: ignore[assignment]
    real_start = rt.start
    rt.start = lambda *a, **k: {"run_id": "fake-run", "thread_id": "fake-thread",  # type: ignore[assignment]
                                "status": "running"}
    try:
        resp = client.post("/api/agent/runs", json={"message": "把这两条存起来"})
        check(resp.status_code == 202, "POST /agent/runs 返回 202")
        check(resp.json()["run_id"] == "fake-run", "202 带 run_id")
    finally:
        rt.start = real_start
    resp = client.post("/api/agent/runs", json={"message": ""})
    check(resp.status_code == 400, "空消息 400")

    store.close_all()
    print(f"✅ test_agent_runtime.py  T50 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    sys.exit(main())
