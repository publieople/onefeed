"""探针：把 Pydantic AI 接到 onefeed 的最小验证（离线脚本模型 + 真模型各跑一遍）。

跑法：uv run python probes/probe_pydantic_ai.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, Field  # noqa: E402
from pydantic_ai import Agent, RunContext  # noqa: E402
from pydantic_ai.messages import (  # noqa: E402
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from onefeed.store import Store  # noqa: E402

DB = ROOT / ".onefeed" / "onefeed.db"
_CJK = re.compile(r"[\u4e00-\u9fff]")
LAST_ROWS: list[dict[str, Any]] = []


def term_hit(term: str, hay: str) -> bool:
    """英文按词边界（AI 不该命中 SAIRfoundation / Kaiser），中文按子串。"""
    t = (term or "").strip().lower()
    if not t:
        return False
    h = hay.lower()
    if _CJK.search(t):
        return t in h
    return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", h) is not None


def search_items(store: Store, terms: list[str], platforms: list[str] | None = None,
                 since: str | None = None, sort: str = "freshness", limit: int = 12,
                 duration_min: int | None = None, like_min: int | None = None) -> list[dict[str, Any]]:
    """改进版检索：多词 OR + 词边界 + 标题加权 + 候选池 60。"""
    ts = None
    if since == "today":
        ts = int(time.time()) - 86400
    elif since == "week":
        ts = int(time.time()) - 7 * 86400
    pool, _ = store.page(platforms=platforms or None, sort="freshness", limit=60, since=ts)
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in pool:
        title = str(row.get("title") or "")
        text = str(row.get("text") or "")
        author = str(row.get("author") or "")
        if duration_min and int(row.get("duration") or 0) < duration_min * 60:
            continue
        if like_min and int(row.get("like_count") or 0) < like_min:
            continue
        score = 0.0
        for term in terms or []:
            if term_hit(term, title):
                score += 3.0
            if term_hit(term, text):
                score += 1.0
            if term_hit(term, author):
                score += 0.2
        if terms and score <= 0:
            continue
        scored.append((score, row))
    if sort == "engagement":
        scored.sort(key=lambda p: (p[0], int(p[1].get("like_count") or 0)), reverse=True)
    else:
        scored.sort(key=lambda p: (p[0], int(p[1].get("published_at") or 0)), reverse=True)
    out: list[dict[str, Any]] = []
    for score, row in scored[: max(1, min(int(limit), 20))]:
        out.append({
            "id": row.get("id"),
            "platform": row.get("platform"),
            "title": str(row.get("title") or "")[:80],
            "text": str(row.get("text") or "")[:100],
            "author": row.get("author"),
            "duration": int(row.get("duration") or 0),
            "like": int(row.get("like_count") or 0),
            "score": round(score, 2),
        })
    return out


class Pick(BaseModel):
    id: str = Field(description="候选里给出的条目 id，必须原样抄")
    why: str = Field("", description="一句话说明为什么相关")


class Answer(BaseModel):
    reply: str = Field(description="一句话回应用户")
    picks: list[Pick] = Field(default_factory=list, description="真正相关的条目，最多 8 条")


@dataclass
class Deps:
    store: Store
    rows: list[dict[str, Any]] = field(default_factory=list)


INSTRUCTIONS = (
    "你是 OneFeed 的找内容 agent。先把用户的问题拆成 1-3 个检索词，调用 search_items 拿候选；"
    "可以多次调用（换词、放宽时间或平台）。从候选里只挑真正相关的，候选里没有相关就少挑或不挑，绝不凑数。"
)


def build_agent(model: Any) -> Agent[Deps, Answer]:
    agent: Agent[Deps, Answer] = Agent(
        model, output_type=Answer, deps_type=Deps, instructions=INSTRUCTIONS,
        model_settings={"temperature": 0.2},
    )

    @agent.tool
    def search(ctx: RunContext[Deps], terms: list[str], platforms: list[str] | None = None,
               since: str | None = None, sort: str = "freshness", limit: int = 12,
               duration_min: int | None = None, like_min: int | None = None) -> list[dict[str, Any]]:
        """在本地库里找内容。terms 是检索词（多个词是 OR）；since 取 today/week；可限时长与点赞。"""
        rows = search_items(ctx.deps.store, terms, platforms, since, sort, limit, duration_min, like_min)
        ctx.deps.rows = rows
        LAST_ROWS[:] = rows
        return rows

    return agent


def scripted(messages: list[Any], info: AgentInfo) -> ModelResponse:
    """离线脚本模型：第一轮调工具，第二轮给结构化结果。"""
    returned = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
    if not returned:
        return ModelResponse(parts=[ToolCallPart("search", {
            "terms": ["AI", "大模型"], "platforms": ["bilibili"], "since": "week", "limit": 6,
        })])
    tool_name = info.output_tools[0].name if info.output_tools else "final_result"
    picks = [{"id": r["id"], "why": "标题命中 " + ("AI" if "AI" in r["title"].upper() else "大模型")}
             for r in LAST_ROWS[:3]]
    return ModelResponse(parts=[ToolCallPart(tool_name, {
        "reply": "挑了几条 B 站这两周讲 AI 的。", "picks": picks,
    })])


def real_model() -> Any:
    conf = json.loads((ROOT / ".onefeed" / "settings.json").read_text("utf-8"))
    for prov in conf.get("ai_providers") or []:
        blob = (str(prov.get("name") or "") + str(prov.get("base_url") or "")).lower()
        secret = prov.get("key") or prov.get("api_key")
        if prov.get("enabled") and secret and "deepseek" in blob:
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider
            return OpenAIChatModel(
                str(prov.get("model") or "deepseek-chat"),
                provider=OpenAIProvider(base_url=str(prov.get("base_url")), api_key=str(secret)),
            )
    return None


def main() -> int:
    store = Store(DB)
    deps = Deps(store=store)
    question = "B站有什么AI相关的比较有含金量的新东西吗"

    offline = build_agent(FunctionModel(scripted))
    res = offline.run_sync(question, deps=deps)
    print("OFFLINE output =", json.dumps(res.output.model_dump(), ensure_ascii=False, indent=2))
    print("OFFLINE tool rows =", [r["title"][:30] for r in LAST_ROWS])

    model = real_model()
    if model is None:
        print("REAL skipped: no deepseek provider in settings.json")
        return 0
    agent = build_agent(model)
    started = time.time()
    res = agent.run_sync(question, deps=Deps(store=store))
    print("REAL ms =", int((time.time() - started) * 1000))
    print("REAL output =", json.dumps(res.output.model_dump(), ensure_ascii=False, indent=2))
    print("REAL tool rows =", [r["title"][:30] for r in LAST_ROWS])
    print("REAL usage =", res.usage())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
