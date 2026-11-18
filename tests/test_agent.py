"""T49 验收：AI agent（模型拿工具自己搜、看结果、自己挑）。

跑法：python tests/test_agent.py [--verbose]

四件事必须成立：
1. 开关关掉（ai_agent=False / ONEFEED_AI_AGENT=0）时完全不 import pydantic_ai，chat 走旧路径；
2. 检索层：英文词边界消掉假命中、标题加权、时长/点赞硬过滤、排除集；
3. agent：工具调一次就能挑，模型编的 id 被丢掉，零挑选照样说人话；
4. agent 挂了（异常 / 超时）静默退回旧路径，用户看不到栈。
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

HOME = ROOT / ".onefeed" / "tmp" / "agent-test-home"
HOME.mkdir(parents=True, exist_ok=True)
for leftover in HOME.glob("settings.json"):
    leftover.unlink(missing_ok=True)
os.environ["ONEFEED_HOME"] = str(HOME)
os.environ.pop("ONEFEED_AI_KEY", None)
os.environ.pop("ONEFEED_AI_AGENT", None)

from fastapi.testclient import TestClient  # noqa: E402

from onefeed import ai as ai_mod  # noqa: E402
from onefeed import settings as settings_mod  # noqa: E402
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
        # id, platform, kind, title, text, hours, duration(s), like, cluster
        ("bilibili:ai1", "bilibili", "video", "五分钟讲懂大模型推理", "AI 大模型 推理", 1, 300, 900, "c1"),
        ("bilibili:ai2", "bilibili", "video", "本地部署 DeepSeek 实录", "显存 量化 部署", 2, 1500, 200, ""),
        ("bilibili:game", "bilibili", "video", "今天聊聊装机", "显卡 said the main rail", 6, 60, 5000, ""),
        ("bilibili:ai3", "bilibili", "video", "AI 绘图的三种做法", "出图 提示词", 3, 600, 800, "c1"),
        ("xiaohongshu:ai1", "xiaohongshu", "images", "用 AI 做了一张海报", "海报 出图", 1, 0, 60, "c1"),
        ("xiaohongshu:life", "xiaohongshu", "images", "周末去了天文馆", "上海 天文馆", 30, 0, 30, ""),
        ("douyin:game", "douyin", "video", "挑战一天封神", "游戏 三角洲", 3, 45, 3000, ""),
        ("zhihu:ai1", "zhihu", "article", "深度学习怎么找 idea 发论文", "科研 idea AI", 4, 0, 120, ""),
        ("zhihu:news", "zhihu", "article", "多地网约车司机称被特惠车逼疯", "网约车 特惠", 5, 0, 400, ""),
    ]
    out = []
    for iid, platform, kind, title, text, hours, duration, like, cluster in rows:
        out.append({
            "id": iid, "platform": platform, "kind": kind, "title": title, "text": text,
            "author": "作者", "cover": "", "url": "https://example.com/" + iid,
            "published_at": NOW - hours * 3600, "duration": duration,
            "like": like, "comment": 3, "share": 0, "view": 1000,
            "tags": [], "extra": {}, "cluster_id": cluster, "fetched_at": NOW,
        })
    return out


def main() -> int:
    db = ROOT / ".onefeed" / "tmp" / "agent-test.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    store.upsert_items(seed())
    client = TestClient(create_app(store))

    # 1) 关掉开关：一行 pydantic_ai 都不许 import
    settings_mod.save({"ai_agent": False})
    resp = client.post("/api/ai/chat", json={"message": "今天 B 站的 AI 视频"}).json()
    check(resp["engine"] == "rules", "ai_agent=False 时走旧路径")
    check(bool(resp["items"]), "旧路径照样出结果")
    check("pydantic_ai" not in sys.modules, "关掉开关后连 import 都没发生")
    check(ai_mod.status()["agent"] is False, "status 如实报告 agent 没开")

    # 1b) 环境变量也能关，且优先于设置
    settings_mod.save({"ai_agent": True})
    os.environ["ONEFEED_AI_AGENT"] = "0"
    check(ai_mod.status()["agent"] is False, "ONEFEED_AI_AGENT=0 压过设置")
    os.environ.pop("ONEFEED_AI_AGENT", None)

    # 1c) 设置校验：工具次数有上下限
    check(settings_mod.validate({"ai_agent_max_tools": 3})["ai_agent_max_tools"] == 3, "工具次数合法值通过")
    for bad in (0, 13, "x"):
        try:
            settings_mod.validate({"ai_agent_max_tools": bad})
            raise AssertionError(f"ai_agent_max_tools={bad} 应该被拒")
        except ValueError:
            pass
    check(True, "越界 / 非整数被拒")

    # 2) 检索层：词边界、加权、硬过滤、排除集
    hits = store.search_items(terms=["AI"], limit=10)
    ids = {h["id"] for h in hits}
    check("bilibili:game" not in ids, "AI 不再命中 said/main/rail（假命中 0）")
    check(ids == {"bilibili:ai1", "bilibili:ai3", "xiaohongshu:ai1", "zhihu:ai1"},
          "只命中真含 AI 的 4 条")
    ranked = store.search_items(terms=["大模型"], limit=10)
    check(ranked and ranked[0]["id"] == "bilibili:ai1", "标题命中（×3）排在正文命中前")
    check(store.search_items(terms=["大模型"], limit=10, duration_min=900) == [], "时长下限真过滤")
    check(store.search_items(terms=["AI"], limit=10, duration_max=360) != [], "时长上限真过滤")
    short = store.search_items(terms=["AI"], limit=10, duration_max=400)
    check(all(int(r.get("duration") or 0) <= 400 for r in short), "上限过滤后没有超时长的")
    liked = [r["id"] for r in store.search_items(terms=["AI"], limit=10, like_min=700)]
    check(set(liked) == {"bilibili:ai1", "bilibili:ai3"}, "点赞下限真过滤（800/900 两条还在）")
    multi = store.search_items(terms=["DeepSeek", "海报"], limit=10)
    check({r["id"] for r in multi} == {"bilibili:ai2", "xiaohongshu:ai1"}, "多词是 OR")
    excluded = store.search_items(terms=["AI"], limit=10, exclude=["bilibili:ai1", "zhihu:ai1"])
    check({r["id"] for r in excluded} == {"bilibili:ai3", "xiaohongshu:ai1"}, "排除集生效")
    check(store.search_items(terms=["量子计算"], limit=10) == [], "没有就返回空，不凑数")

    # 3) agent 直接跑：工具一次 -> 结构化挑 -> 编的 id 丢掉
    from onefeed import agent as agent_mod  # 到这里才 import pydantic_ai
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    captured: list[list[dict]] = []
    real_search = store.search_items

    def spy(*args, **kwargs):
        rows = real_search(*args, **kwargs)
        captured.append(rows)
        return rows

    store.search_items = spy  # type: ignore[method-assign]

    def scripted(messages, info: AgentInfo) -> ModelResponse:
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("search", {
                "terms": ["AI"], "platforms": ["bilibili"], "limit": 5})])
        tool_name = info.output_tools[0].name
        picks = [{"id": r["id"], "why": "标题讲 AI"} for r in captured[-1][:2]]
        picks.append({"id": "bilibili:ghost", "why": "我编的"})
        return ModelResponse(parts=[ToolCallPart(tool_name, {
            "reply": "B 站这几条讲 AI 的比较实在。", "picks": picks})])

    out = agent_mod.run(store, "B 站有什么 AI 的", model=FunctionModel(scripted), max_tools=4)
    check(out["engine"] == "agent", "agent 路径标记 engine=agent")
    check(out["steps"] == 1, "一次检索就够")
    check([i["id"] for i in out["items"]] == [r["id"] for r in captured[0][:2]],
          "挑的条目顺序照模型给的")
    check(all(i["id"] != "bilibili:ghost" for i in out["items"]), "模型编的 id 被丢掉")
    check("AI" in out["plan"]["keyword"], "计划里留下最有代表性的词")
    check(out["count"] == len(out["items"]) and bool(out["reply"]), "count / reply 都对得上")

    # 3a2) 模型的口语化参数：平台别名、sort=likes、时长按秒
    def loose(messages, info: AgentInfo) -> ModelResponse:
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("search", {
                "terms": ["AI"], "platforms": ["B站", "b站"], "sort": "likes",
                "duration_max_sec": 700, "limit": 5})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "reply": "按 B 站十分钟内挑的。",
            "picks": [{"id": returned[0].content[0]["id"], "why": "符合"}]})])

    loose_out = agent_mod.run(store, "B 站十分钟内的 AI", model=FunctionModel(loose))
    check(loose_out["plan"]["platforms"] == ["bilibili"], "「B站」别名归一成 bilibili")
    check(loose_out["plan"]["sort"] == "engagement", "sort=likes 归一成 engagement")
    check(loose_out["count"] == 1 and loose_out["items"][0]["duration"] <= 700,
          "duration_max_sec 按秒生效")

    # 3b) 零挑选：候选为空时说人话，不硬凑
    def pick_none(messages, info: AgentInfo) -> ModelResponse:
        returned = [p for m in messages for p in getattr(m, "parts", [])
                    if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("search", {"terms": ["量子计算"]})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "reply": "库里没有量子计算的内容，要不要换个词？", "picks": []})])

    none = agent_mod.run(store, "找量子计算", model=FunctionModel(pick_none))
    check(none["count"] == 0 and "量子" in none["reply"], "挑 0 条时说人话")

    # 3c) 超时：慢慢答 -> 抛 TimeoutError 交给上层降级
    def sleepy(messages, info: AgentInfo) -> ModelResponse:
        time.sleep(2)
        return ModelResponse(parts=[])

    try:
        agent_mod.run(store, "慢", model=FunctionModel(sleepy), timeout=0.4)
        raise AssertionError("应该超时")
    except TimeoutError:
        check(True, "超过 timeout 直接抛，不无限等")

    # 3d) TestModel 冒烟：不调工具也能给出结构化答案
    from pydantic_ai.models.test import TestModel
    smoke = agent_mod.run(store, "随便看看", model=TestModel(call_tools=[]))
    check(smoke["engine"] == "agent" and isinstance(smoke["reply"], str), "TestModel 冒烟通过")

    store.search_items = real_search  # type: ignore[method-assign]

    # 4) 接进 API：agent 结果原样透出
    settings_mod.save({"ai_agent": True, "ai_providers": [
        {"id": "p1", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
         "model": "deepseek-chat", "key": "sk-test-secret", "enabled": True},
    ]})
    fake = dict(out)
    real_run = agent_mod.run
    agent_mod.run = lambda *a, **kw: dict(fake)  # type: ignore[assignment]
    try:
        via_api = client.post("/api/ai/chat", json={"message": "B 站 AI"}).json()
        check(via_api["engine"] == "agent", "API 层走 agent 时如实标 engine")
        check(via_api["plan"]["mode"] == "agent", "plan 带 agent 标记")
        check(ai_mod.status()["agent"] is True, "status 报告 agent 可用")

        # 4b) agent 抛错 -> 静默退回旧路径，不把栈丢给用户
        def boom(*args, **kwargs):
            raise RuntimeError("模型 401")

        agent_mod.run = boom  # type: ignore[assignment]
        real_chat = ai_mod._chat
        ai_mod._chat = lambda provider, messages: json.dumps({
            "mode": "find", "platforms": ["bilibili"], "kinds": ["video"],
            "since": None, "keyword": "AI", "sort": "freshness", "reply": "退回旧路径了"})
        try:
            fell = client.post("/api/ai/chat", json={"message": "B 站 AI"}).json()
            check(fell["engine"] == "llm", "agent 挂了之后落回 llm 计划路径")
            check(fell["reply"] == "退回旧路径了", "回落结果仍是完整回答")
            check(ai_mod.status()["last"]["ok"] is True, "降级后那次成功被记下来")
        finally:
            ai_mod._chat = real_chat
    finally:
        agent_mod.run = real_run  # type: ignore[assignment]

    print(f"✅ test_agent.py  T49 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
