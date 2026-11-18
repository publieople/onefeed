"""Agent 化的 AI 助手（P1）。

与旧路径（ai.plan 出一次 JSON 计划 → store.page 做单子串 LIKE）的区别只有一点：
模型手里有工具，可以先搜、看到结果、换词再搜、挑完再答。挑的时候必须交 id，
宿主只认真实存在于候选里的 id —— 编不出来。

落回策略：任何异常（模型挂了、超时、结构化输出坏掉、工具次数超限）都由
ai.chat 捕获后退回旧路径，用户看到的永远是完整回答，不会看到栈。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import UsageLimits

from . import smart

TIMEOUT = 45.0
MAX_PICKS = 8
MAX_TERMS = 6

INSTRUCTIONS = """你在 OneFeed 里帮用户从「本地聚合库」找内容。库里有六个平台（B 站、小红书、抖音、
掘金、V2EX、知乎），每条含标题、正文、作者、时长、点赞、发布时间。

工作方式：
1. 先把用户的话拆成 1-3 个检索词，调 search 拿候选（多个词是 OR）。第一轮别急着答。
2. 看过候选再决定：换词、放宽平台/时间、或加时长/点赞过滤，可以再搜。最多调 6 次工具。
3. 只从工具返回过的候选里挑，id 必须原样抄。候选里没有相关就少挑或不挑，绝不凑数。
4. 用户说的平台、时间、时长、点赞是硬条件：要么在工具参数里生效，要么在 reply 里明说做不到。
   platforms 只填 id：bilibili / xiaohongshu / douyin / juejin / v2ex / zhihu / zhihu-hot，不要写「B站」。
   duration_min_sec / duration_max_sec 的单位是**秒**，「十分钟以内」= 600。
5. reply 一句话（40 字以内），说清你挑了什么、条件是什么；不客套、不复读原话。
6. picks 最多 8 条，按相关度排；每条 why 一句话说为什么相关。
"""


class Pick(BaseModel):
    id: str = Field(description="候选里给出的条目 id，原样抄，不要改")
    why: str = Field("", description="一句话说明为什么相关")


class Answer(BaseModel):
    reply: str = Field(description="一句话回应用户，40 字以内")
    picks: list[Pick] = Field(default_factory=list, description="真正相关的条目，最多 8 条")


@dataclass
class Deps:
    """一次问答里的状态：见过的条目、调过几次工具、用过哪些条件。"""

    store: Any
    limit: int = 12
    exclude: tuple[str, ...] = ()
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: int = 0
    terms: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    since_ts: int | None = None
    sort: str = "freshness"
    seen: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


# ---------------------------------------------------------------- 参数归一化

_PLATFORM_IDS = set(smart.PLATFORM_LABELS)
_PLATFORM_ALIAS = {alias.lower(): pid for pid, alts in smart.PLATFORM_ALIASES.items() for alias in alts}
_PLATFORM_ALIAS.update({pid: pid for pid in _PLATFORM_IDS})

_SORT_ALIAS = {
    "hot": "engagement", "likes": "engagement", "like": "engagement", "popular": "engagement",
    "最热": "engagement", "热度": "engagement", "engagement": "engagement",
    "new": "freshness", "latest": "freshness", "fresh": "freshness", "最新": "freshness",
    "freshness": "freshness",
}

_KIND_ALIAS = {alias: pid for pid, alts in smart.KIND_ALIASES.items() for alias in alts}
_KIND_IDS = set(smart.KIND_ALIASES)


def _norm_platforms(values: Sequence[str] | None) -> list[str]:
    """模型爱写「B站」「b站」，SQL 只认 bilibili —— 这里统一收口，别让别名变成 0 结果。"""
    out: list[str] = []
    for value in values or []:
        key = str(value or "").strip().lower().replace(" ", "")
        pid = _PLATFORM_ALIAS.get(key) or (key if key in _PLATFORM_IDS else "")
        if pid and pid not in out:
            out.append(pid)
    return out


def _norm_kinds(values: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        key = str(value or "").strip().lower()
        kid = _KIND_ALIAS.get(key) or (key if key in _KIND_IDS else "")
        if kid and kid not in out:
            out.append(kid)
    return out


def _norm_sort(value: str | None) -> str:
    return _SORT_ALIAS.get(str(value or "").strip().lower(), "freshness")


def _cache_key(terms: list[str], platforms: list[str], kinds: list[str], since: str | None,
               sort: str, limit: int, dmin: int | None, dmax: int | None,
               like_min: int | None) -> str:
    return "|".join([",".join(terms), ",".join(platforms), ",".join(kinds), str(since), sort,
                     str(limit), str(dmin), str(dmax), str(like_min)])


# ---------------------------------------------------------------- 模型

def _models(chain: Sequence[dict[str, Any]]) -> Any:
    """把顺序表变成 pydantic-ai 的模型链：第一个挂了自动换下一个。"""
    from pydantic_ai.models.fallback import FallbackModel
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    built = [
        OpenAIChatModel(str(p["model"]),
                        provider=OpenAIProvider(base_url=str(p["base_url"]), api_key=str(p["key"])))
        for p in chain
    ]
    if not built:
        raise RuntimeError("没有配置模型 key")
    return built[0] if len(built) == 1 else FallbackModel(*built)


def _since_ts(since: str | None) -> int | None:
    if since == "today":
        return int(time.time()) - 86400
    if since == "week":
        return int(time.time()) - 7 * 86400
    return None


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    """给模型看的紧凑条目：省 token，但把判断相关性要用的字段都留着。"""
    duration = int(row.get("duration") or 0)
    published = int(row.get("published_at") or 0)
    return {
        "id": row.get("id"),
        "platform": row.get("platform"),
        "kind": row.get("kind"),
        "title": str(row.get("title") or "")[:80],
        "author": str(row.get("author") or "")[:20],
        "text": str(row.get("text") or "")[:120],
        "minutes": round(duration / 60) if duration else 0,
        "like": int(row.get("like_count") or 0),
        "hours_ago": max(0, round((time.time() - published) / 3600)) if published else 0,
    }


def build_agent(model: Any, max_tools: int = 6) -> Any:
    agent = Agent(model, output_type=Answer, deps_type=Deps, instructions=INSTRUCTIONS,
                  model_settings={"temperature": 0.2})

    @agent.tool
    def search(ctx: RunContext[Deps], terms: list[str] | None = None,
               platforms: list[str] | None = None, kinds: list[str] | None = None,
               since: str | None = None, sort: str = "freshness", limit: int = 10,
               duration_min_sec: int | None = None, duration_max_sec: int | None = None,
               like_min: int | None = None) -> list[dict[str, Any]]:
        """在本地库找内容。terms 是检索词（多个词是 OR，英文按词边界）；since 取 today/week；
        duration_min_sec / duration_max_sec 是时长下限 / 上限，**单位秒**（10 分钟 = 600）；
        like_min 是最少点赞。返回候选列表；每次回答最多调 max_tools 次。"""
        deps = ctx.deps
        if deps.calls >= max_tools:
            return [{"error": f"已用满 {max_tools} 次检索，不要再搜了，直接用现有候选回答。"}]
        clean = [str(t).strip() for t in (terms or []) if str(t or "").strip()][:MAX_TERMS]
        pids = _norm_platforms(platforms)
        kids = _norm_kinds(kinds)
        order = _norm_sort(sort)
        size = max(1, min(int(limit or 10), 20))
        since_ts = _since_ts(since)
        key = _cache_key(clean, pids, kids, since, order, size,
                         duration_min_sec, duration_max_sec, like_min)
        deps.calls += 1
        if key in deps.seen:  # 同一条件重复搜：直接回放，省一次往返
            return [_brief(r) for r in deps.seen[key]]
        rows = deps.store.search_items(
            terms=clean, platforms=pids or None, kind=None, sort=order,
            limit=size, since=since_ts,
            duration_min=duration_min_sec, duration_max=duration_max_sec,
            like_min=like_min, exclude=deps.exclude)
        if kids:
            wanted = set(kids)
            rows = [r for r in rows if str(r.get("kind")) in wanted]
        deps.terms.extend(t for t in clean if t not in deps.terms)
        for row in rows:
            deps.rows[str(row.get("id"))] = row
        for pid in pids:
            if pid not in deps.platforms:
                deps.platforms.append(pid)
        for kid in kids:
            if kid not in deps.kinds:
                deps.kinds.append(kid)
        if since_ts:
            deps.since_ts = since_ts
        deps.sort = order
        briefs = [_brief(r) for r in rows]
        deps.seen[key] = rows
        return briefs

    @agent.tool
    def get_item(ctx: RunContext[Deps], item_id: str) -> dict[str, Any]:
        """看某一条的完整正文（候选摘要只有 120 字）。id 用候选里给的。"""
        row = ctx.deps.rows.get(str(item_id))
        if row is None:
            found = ctx.deps.store.get_item(str(item_id))
            if found is None:
                return {"error": "没有这个 id，请只用候选里出现过的 id"}
            row = found
            ctx.deps.rows[str(row.get("id"))] = row
        brief = _brief(row)
        brief["text"] = str(row.get("text") or "")[:600]
        brief["url"] = str(row.get("url") or "")[:200]
        return brief

    @agent.tool
    def similar(ctx: RunContext[Deps], item_id: str, limit: int = 4) -> list[dict[str, Any]]:
        """「多来点这个」：同一件事在其它平台的说法（按 cluster_id 找）。"""
        row = ctx.deps.rows.get(str(item_id)) or ctx.deps.store.get_item(str(item_id))
        if not row:
            return []
        rows = ctx.deps.store.cluster_items(str(row.get("cluster_id") or ""),
                                            exclude_id=str(row.get("id")), limit=limit)
        rows = [r for r in rows if str(r.get("id")) not in set(ctx.deps.exclude)]
        for r in rows:
            ctx.deps.rows[str(r.get("id"))] = r
        return [_brief(r) for r in rows]

    return agent


# ---------------------------------------------------------------- 历史与超时

def _messages(history: list[dict[str, str]] | None) -> list[Any]:
    """把前端传来的 [{role, text, plan}] 变成真消息序列，让模型记得上一轮聊到哪。"""
    if not history:
        return []
    out: list[Any] = []
    for turn in list(history)[-6:]:
        text = str(turn.get("text") or turn.get("content") or "")[:300]
        if not text:
            continue
        if turn.get("role") == "user":
            out.append(ModelRequest(parts=[UserPromptPart(content=text)]))
        else:
            out.append(ModelResponse(parts=[TextPart(content=text)]))
    return out


def _previous(history: list[dict[str, str]] | None) -> str:
    """上一轮的检索条件写成一句话塞进本轮提问：追问「换成最热的」时模型才知道在改什么。"""
    prev: dict[str, Any] | None = None
    for turn in reversed(history or []):
        plan = turn.get("plan")
        if isinstance(plan, dict) and (plan.get("platforms") or plan.get("keyword")):
            prev = plan
            break
    if not prev:
        return ""
    bits: list[str] = []
    if prev.get("platforms"):
        bits.append("平台 " + "、".join(str(p) for p in prev["platforms"]))
    if prev.get("kinds"):
        bits.append("类型 " + "、".join(str(k) for k in prev["kinds"]))
    if prev.get("keyword"):
        bits.append("关键词「" + str(prev["keyword"]) + "」")
    if prev.get("since"):
        bits.append("只要近一天")
    if not bits:
        return ""
    return "（上一轮的条件：" + "，".join(bits) + "；可以沿用，也可以改。）"


def _with_timeout(fn, timeout: float) -> Any:
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样交给调用方决定降级
            box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True, name="onefeed-agent")
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"agent 超过 {timeout:.0f}s 没答完")
    if "error" in box:
        raise box["error"]
    return box["value"]


# ---------------------------------------------------------------- 组装回答

def _label(pid: str) -> str:
    return smart.PLATFORM_LABELS.get(pid, pid)


def _pick_rows(deps: Deps, answer: Answer) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pick in answer.picks[:MAX_PICKS]:
        item_id = str(pick.id or "").strip()
        row = deps.rows.get(item_id)
        if row is None or item_id in seen:  # 模型编的 id / 重复的 id：丢掉，不替它圆
            continue
        seen.add(item_id)
        item = dict(row)
        reasons = [str(pick.why or "").strip()[:40]] if str(pick.why or "").strip() else []
        for reason in smart.reason_for(item, {}):
            if reason and reason not in reasons:
                reasons.append(reason)
        item["reasons"] = reasons[:3]
        out.append(item)
    return out


def _best_term(deps: Deps) -> str:
    """挑一个最有代表性的词当计划的 keyword：前端「用这个条件刷」还走旧 LIKE，
    塞一串 OR 词进去必然搜不到，不如只留一个最准的。"""
    best, hits = "", -1
    for term in deps.terms:
        count = sum(1 for row in deps.rows.values()
                    if deps.store._hit_score([term], row) > 0)
        if count > hits:
            best, hits = term, count
    return best


def _plan(deps: Deps) -> dict[str, Any]:
    return {
        "mode": "agent",
        "platforms": list(deps.platforms),
        "kinds": list(deps.kinds),
        "since": deps.since_ts,
        "keyword": _best_term(deps),
        "sort": deps.sort,
    }


def _understood(pl: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    bits: list[str] = ["AI 挑的"]
    if pl["platforms"]:
        bits.append("、".join(_label(p) for p in pl["platforms"]))
    if pl["keyword"]:
        bits.append("含「" + pl["keyword"] + "」")
    if pl["since"]:
        bits.append("近一天")
    if not pl["platforms"] and not pl["keyword"] and rows:
        first = str(rows[0].get("platform") or "")
        if first:
            bits.append(_label(first))
    return " · ".join(bits)


def _suggestions(deps: Deps, rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    if len(deps.platforms) != 1 and rows:
        first = str(rows[0].get("platform") or "")
        if first:
            out.append("只看 " + _label(first))
    out.append("换成最新的" if deps.sort == "engagement" else "换成最热的")
    if not deps.since_ts:
        out.append("只要今天的")
    return out[:3]


def _reply(answer: Answer, rows: list[dict[str, Any]]) -> str:
    said = str(answer.reply or "").strip()[:80]
    if said:
        return said
    if not rows:
        return "按你的条件没在本地库里找到相关的内容，换个说法试试。"
    return f"挑了 {len(rows)} 条，都是从候选里筛出来的。"


def run(store: Any, message: str, history: list[dict[str, str]] | None = None,
        limit: int = 12, exclude: list[str] | None = None,
        chain: Sequence[dict[str, Any]] | None = None, max_tools: int = 6,
        model: Any = None, timeout: float = TIMEOUT) -> dict[str, Any]:
    """跑一轮 agent。任何失败直接抛，由 ai.chat 落回旧路径。"""
    message = (message or "").strip()[:200]
    if not message:
        raise ValueError("空问题")
    max_tools = max(1, min(int(max_tools or 6), 12))
    deps = Deps(store=store, limit=limit, exclude=tuple(exclude or ()))
    built = build_agent(model if model is not None else _models(chain or []), max_tools=max_tools)
    prompt = message
    previous = _previous(history)
    if previous:
        prompt = message + "\n\n" + previous
    started = time.time()
    result = _with_timeout(
        lambda: built.run_sync(
            prompt, deps=deps, message_history=_messages(history),
            # tool_calls_limit 比 max_tools 宽：模型一回合并行发多个工具调用时，别让它撞硬墙
            # 整轮失败（软预算在 search 里已经拦住了）。request_limit 兜住死循环。
            usage_limits=UsageLimits(request_limit=max_tools + 4,
                                     tool_calls_limit=max(12, max_tools + 6)),
        ),
        timeout)
    answer: Answer = result.output
    rows = _pick_rows(deps, answer)[: max(1, min(int(limit), 24))]
    pl = _plan(deps)
    usage = getattr(result, "usage", None)
    return {
        "engine": "agent",
        "provider": str((chain or [{}])[0].get("name", "")) if chain else "脚本模型",
        "plan": pl,
        "reply": _reply(answer, rows),
        "items": rows,
        "count": len(rows),
        "suggestions": _suggestions(deps, rows),
        "understood": _understood(pl, rows),
        "steps": deps.calls,
        "ms": int((time.time() - started) * 1000),
        "tokens": int(getattr(usage, "total_tokens", 0) or 0) if usage is not None else 0,
    }
