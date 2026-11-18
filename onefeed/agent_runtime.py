"""运行器（011 P0）：把 Agent 跑成一条可观察、可回放的运行。

分工：
- 这里管生命周期（run_id / 预算 / 确认 / 取消）、事件落库、模型接线；
- 动作本身在 actions.py（白名单 + 分级 + undo）；
- 事件流不另开内存总线：每一步先写 agent_steps，SSE 按 seq 从库里读。
  这样「实时看」和「刷新回放」是同一条路径，断线重连天然支持 Last-Event-ID。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from pydantic_ai import Agent, RunContext

from . import actions as act_mod
from . import smart
from .agent import Answer, Pick, _messages, _models, _previous, _with_timeout

MAX_STEPS = 12
MAX_SECONDS = 120.0
MAX_TOOL_CALLS = 10

INSTRUCTIONS = """你是 OneFeed 的助手，能操作这个应用，不只是查库。

规矩：
1. 先想清楚要做几件事，再动手：找内容用 search_items，看细节用 get_item，
   要改界面用 ui_*，要存起来用 save_item，要总结用 summarize_item / summarize_batch，
   要成文件用 export_markdown。
2. 一次 run 最多 10 次动作、12 步、120 秒。检索类动作（search/get/similar/feed_stats）
   加起来最多 4 次：拿到 3-5 条能用的就停下来做正事，不要反复换词搜同一个东西。
   单次总结可能要十几秒：一次只总结你真正要用的几条（批量上限 6），把时间留给 summarize 和 export。
3. 只能挑检索结果里出现过的 id，原样抄，不许编。宁可少给，不许凑数。
4. 用户提到平台/时间/时长/点赞，要么真的生效，要么在 reply 里说清没做到哪条。
5. 结果少（≤2 条）就说明为什么少：是库里没有、条件太窄，还是时间太新。
6. reply 是给人看的一句话（≤60 字），不要复述步骤；picks 按相关度排，最多 8 条。
7. 用户让你「存起来 / 收藏」就直接调 save_item；让你「切到某平台看」就调 ui_filter。
8. 用户要「简报 / 总结成 md / 导出」是两步活：summarize_item（1 条）或 summarize_batch（多条）
   → 紧接着 export_markdown。中间不要再搜一遍、不要再刷新采集；回报里给出文件路径即可，
   别把正文念一遍。总结失败或某条没正文时，说清是哪条没成，不要编内容。
9. 用户没明说「刷新 / 更新 / 再抓一次」，就不要调 refresh_feed：它会等确认、耽误几十秒。
   检索结果不够时，先换词、放宽条件，或在 reply 里说明。"""


# ---------------------------------------------------------------- 运行状态
@dataclass
class RunState:
    run_id: str
    thread_id: str = ""
    seq: int = 0
    cancel: bool = False
    started: float = field(default_factory=time.time)
    pending: dict[str, threading.Event] = field(default_factory=dict)
    decisions: dict[str, bool] = field(default_factory=dict)


_STATES: dict[str, RunState] = {}
_STATES_LOCK = threading.Lock()


def get_state(run_id: str) -> RunState | None:
    with _STATES_LOCK:
        return _STATES.get(run_id)


def cancel(run_id: str) -> bool:
    state = get_state(run_id)
    if state is None:
        return False
    state.cancel = True
    for event in list(state.pending.values()):
        event.set()
    return True


def resolve_confirm(run_id: str, confirm_id: str, allow: bool) -> bool:
    state = get_state(run_id)
    if state is None:
        return False
    state.decisions[confirm_id] = bool(allow)
    event = state.pending.get(confirm_id)
    if event is None:
        return False
    event.set()
    return True


@dataclass
class Deps:
    ctx: act_mod.Ctx
    store: Any
    limit: int = 12
    exclude: tuple[str, ...] = ()
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: int = 0
    max_tool_calls: int = MAX_TOOL_CALLS
    applied: list[dict[str, Any]] = field(default_factory=list)
    looked: list[str] = field(default_factory=list)
    query: dict[str, Any] = field(default_factory=dict)
    budget_hit: bool = False
    deadline: float = 0.0  # 本轮整段的硬截止（time.time() 基准），确认等待不能吃穿它
    searches: int = 0  # 检索类动作已用次数；上限固定，避免模型把预算全花在反复搜
    search_hit: bool = False

    def remember(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            item_id = str(row.get("id") or "")
            if item_id:
                self.rows[item_id] = row


# ---------------------------------------------------------------- 事件
class EventWriter:
    """把事件按 seq 写进 agent_steps，同时把内容推给前端（前端只读库）。"""

    def __init__(self, store: Any, state: RunState):
        self.store = store
        self.state = state
        self._lock = threading.Lock()

    def emit(self, kind: str, name: str = "", payload: dict[str, Any] | None = None,
             undo_token: str = "") -> int:
        with self._lock:
            self.state.seq += 1
            seq = self.state.seq
            self.store.add_agent_step(self.state.run_id, seq, kind, name, payload, undo_token)
        return seq


def events_after(store: Any, run_id: str, after: int = 0) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT seq, kind, name, payload, undo_token, at FROM agent_steps "
        "WHERE run_id = ? AND seq > ? ORDER BY seq", (run_id, int(after))).fetchall()
    return [store._decode_step(dict(r)) for r in rows]


def sse_stream(store: Any, run_id: str, after: int = 0,
               timeout: float = 120.0) -> Iterator[str]:
    """SSE：先补发 last_id 之后的事件，再按 0.2s 轮询新事件，15s 心跳。"""
    deadline = time.time() + max(5.0, timeout)
    last = int(after)
    idle = 0.0
    yield "retry: 1500\n\n"
    while True:
        for step in events_after(store, run_id, last):
            last = int(step["seq"])
            body = {"seq": last, "kind": step["kind"], "name": step["name"],
                    "data": step["data"], "undo_token": step["undo_token"], "at": step["at"]}
            yield f"id: {last}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"
            idle = 0.0
        run = store.get_agent_run(run_id, steps=False)
        if run is None:
            yield f"event: error\ndata: {json.dumps({'message': 'run 不存在'}, ensure_ascii=False)}\n\n"
            return
        if run.get("status") != "running":
            return
        if time.time() > deadline:
            return
        time.sleep(0.2)
        idle += 0.2
        if idle >= 15.0:
            idle = 0.0
            yield ": keep-alive\n\n"


# ---------------------------------------------------------------- 预算 + 动作
def _budget_error(deps: Deps, why: str) -> dict[str, Any]:
    deps.budget_hit = True
    note = f"预算用尽（{why}），不要再调动作了，直接按现有结果给结论。"
    return {"ok": False, "error": note}


_ACTION_LOCK = threading.Lock()

# 翻库类动作单轮上限：总结/导出才是正事，别让模型把 10 次预算全用来换词重搜
SEARCH_FAMILY = ("search_items", "get_item", "similar_items", "feed_stats")
MAX_SEARCHES = 4


def _run_action(deps: Deps, writer: EventWriter, name: str,
                args: dict[str, Any]) -> dict[str, Any]:
    """一次动作调用：预算 → 执行 → tool 事件（含耗时与结果预览）。"""
    # 模型会并发发多个工具调用；预算判断与计数必须在锁里，否则会同时超限、提示两遍
    with _ACTION_LOCK:
        over = deps.calls >= deps.max_tool_calls
        first_note = over and not deps.budget_hit
        if over:
            deps.budget_hit = True
        else:
            deps.calls += 1
        search_over = (not over and name in SEARCH_FAMILY
                       and deps.searches >= MAX_SEARCHES)
        first_search_note = search_over and not deps.search_hit
        if search_over:
            deps.search_hit = True
        elif not over and name in SEARCH_FAMILY:
            deps.searches += 1
    if over:
        if first_note:
            writer.emit("step", "budget", {"title": "动作次数用满", "kind": "note"})
        return _budget_error(deps, "动作次数")
    if search_over:
        if first_search_note:
            writer.emit("step", "search_cap", {"title": "检索够了，先用手上这些", "kind": "note"})
        writer.emit("tool", name, {"ok": False, "ms": 0,
                                   "args": json.dumps(args, ensure_ascii=False)[:300],
                                   "result": f"检索次数用满（{MAX_SEARCHES} 次）"})
        return {"ok": False,
                "error": f"检索类动作已经用了 {MAX_SEARCHES} 次，够用了："
                         f"直接用已拿到的条目做 summarize/export/回答。"}
    started = time.time()
    preview = json.dumps(args, ensure_ascii=False)[:300]
    writer.emit("step", name, {"title": _title_for(name, args), "kind": "tool",
                               "detail": preview})
    try:
        result = act_mod.call(deps.ctx, name, args)
    except act_mod.ConfirmRequired as need:
        _await_confirm(deps, writer, need)
        return {"ok": False, "error": f"用户没允许 {need.action}，用现有数据继续"}
    except act_mod.ActionError as exc:
        writer.emit("tool", name, {"ok": False, "ms": int((time.time() - started) * 1000),
                                   "args": preview, "result": str(exc)[:300]})
        return {"ok": False, "error": str(exc)}
    ms = int((time.time() - started) * 1000)
    rows = result.get("items") if isinstance(result, dict) else None
    if isinstance(rows, list):
        deps.remember(rows)
        if name == "search_items" and result.get("query"):
            deps.query = result["query"]
    if name.startswith("ui_") or name in ("save_item", "mark_read", "export_markdown"):
        deps.applied.append({"name": name, "ms": ms, "ok": bool(result.get("ok", True))})
    writer.emit("tool", name, {"ok": bool(result.get("ok", True)), "ms": ms,
                               "args": preview,
                               "result": json.dumps(result, ensure_ascii=False)[:400]})
    return result


def _title_for(name: str, args: dict[str, Any]) -> str:
    if name == "search_items":
        terms = "、".join(str(t) for t in (args.get("terms") or [])) or "候选池"
        plats = "、".join(act_mod.norm_platforms(args.get("platforms"))) or "全平台"
        return f"检索「{terms}」· {plats}"
    if name == "get_item":
        return f"看详情 {args.get('id')}"
    if name == "similar_items":
        return f"找同题 {args.get('id')}"
    if name == "feed_stats":
        return "看库里的规模"
    if name == "ui_filter":
        return "切换筛选条件"
    if name == "ui_navigate":
        return f"跳到 {args.get('page')}"
    if name == "ui_open_item":
        return f"打开 {args.get('id')}"
    if name == "ui_toast":
        return "给一句提示"
    if name == "save_item":
        return f"收藏 {args.get('id')}"
    if name == "mark_read":
        return f"标记 {args.get('state')}"
    if name == "refresh_feed":
        return "触发采集刷新"
    if name == "summarize_item":
        return f"总结 {args.get('id')}"
    if name == "summarize_batch":
        count = len(args.get("ids") or [])
        return f"批量总结 {count} 条"
    if name == "export_markdown":
        title = str(args.get("title") or "").strip()
        return f"导出 md{('「' + title + '」') if title else ''}"
    return name


def _await_confirm(deps: Deps, writer: EventWriter, need: act_mod.ConfirmRequired,
                   timeout: float = 60.0) -> str:
    """L3 动作：发 need_confirm，等前端点允许/拒绝。超时按拒绝处理。"""
    state = writer.state
    confirm_id = uuid.uuid4().hex[:12]
    event = threading.Event()
    state.pending[confirm_id] = event
    writer.emit("need_confirm", need.action, {"confirm_id": confirm_id,
                                             "action": need.action,
                                             "summary": need.summary,
                                             "risk": need.risk})
    # 等人点确认不能把整轮预算吃光：最多等到「硬截止前 10 秒」，没算截止就用原值
    wait = timeout
    if deps.deadline:
        wait = max(5.0, min(timeout, deps.deadline - time.time() - 10.0))
    event.wait(wait)
    state.pending.pop(confirm_id, None)
    allowed = bool(state.decisions.pop(confirm_id, False))
    if allowed:
        state_allowed = getattr(state, "confirmed", None)
        if state_allowed is None:
            state.confirmed = set()
        state.confirmed.add(need.action)
        deps.ctx.confirmed.add(need.action)
    return confirm_id


# ---------------------------------------------------------------- 模型接线
def build_agent(model: Any, deps: Deps, writer: EventWriter, max_tools: int) -> Any:
    agent = Agent(model, output_type=Answer, deps_type=Deps, instructions=INSTRUCTIONS,
                  model_settings={"temperature": 0.2})

    @agent.tool
    def search_items(ctx: RunContext[Deps], terms: list[str] | None = None,
                     platforms: list[str] | None = None, kinds: list[str] | None = None,
                     since: str | None = None, sort: str = "freshness", limit: int = 10,
                     duration_min_sec: int | None = None, duration_max_sec: int | None = None,
                     like_min: int | None = None) -> dict[str, Any]:
        """检索本地库。多词是「或」；limit 上限 30。"""
        return _run_action(deps, writer, "search_items", {
            "terms": terms, "platforms": platforms, "kinds": kinds, "since": since,
            "sort": sort, "limit": limit, "duration_min_sec": duration_min_sec,
            "duration_max_sec": duration_max_sec, "like_min": like_min})

    @agent.tool
    def get_item(ctx: RunContext[Deps], id: str) -> dict[str, Any]:
        """看一条的正文（截 600 字）。id 必须来自检索结果。"""
        return _run_action(deps, writer, "get_item", {"id": id})

    @agent.tool
    def similar_items(ctx: RunContext[Deps], id: str, limit: int = 4) -> dict[str, Any]:
        """同一条在其它平台的说法（cluster_id 聚合）。"""
        return _run_action(deps, writer, "similar_items", {"id": id, "limit": limit})

    @agent.tool
    def feed_stats(ctx: RunContext[Deps], platform: str = "") -> dict[str, Any]:
        """本地库总条数与平台分布。"""
        return _run_action(deps, writer, "feed_stats", {"platform": platform})

    @agent.tool
    def ui_filter(ctx: RunContext[Deps], platforms: list[str] | None = None,
                  sort: str = "freshness", since: str = "", keyword: str = "",
                  kinds: list[str] | None = None) -> dict[str, Any]:
        """改 feed 的筛选（前端立刻生效，不用等）。"""
        return _run_action(deps, writer, "ui_filter", {
            "platforms": platforms, "sort": sort, "since": since,
            "keyword": keyword, "kinds": kinds})

    @agent.tool
    def ui_navigate(ctx: RunContext[Deps], page: str = "feed", id: str = "") -> dict[str, Any]:
        """跳页：feed / item / settings / market / saved。"""
        return _run_action(deps, writer, "ui_navigate", {"page": page, "id": id})

    @agent.tool
    def ui_open_item(ctx: RunContext[Deps], id: str) -> dict[str, Any]:
        """在前端打开某条的详情抽屉。"""
        return _run_action(deps, writer, "ui_open_item", {"id": id})

    @agent.tool
    def ui_toast(ctx: RunContext[Deps], text: str, level: str = "info") -> dict[str, Any]:
        """给用户一条即时提示。"""
        return _run_action(deps, writer, "ui_toast", {"text": text, "level": level})

    @agent.tool
    def save_item(ctx: RunContext[Deps], id: str, on: bool = True) -> dict[str, Any]:
        """收藏（on=false 取消）。落库，刷新还在。"""
        return _run_action(deps, writer, "save_item", {"id": id, "on": on})

    @agent.tool
    def mark_read(ctx: RunContext[Deps], ids: list[str], state: str = "read") -> dict[str, Any]:
        """已读 / 不感兴趣：state=read/unread/hide/unhide。"""
        return _run_action(deps, writer, "mark_read", {"ids": ids, "state": state})

    @agent.tool
    def refresh_feed(ctx: RunContext[Deps], platforms: list[str] | None = None) -> dict[str, Any]:
        """触发一次采集并等它跑完（几十秒）。会打外网，需要用户确认。"""
        return _run_action(deps, writer, "refresh_feed", {"platforms": platforms})

    @agent.tool
    def summarize_item(ctx: RunContext[Deps], id: str, force: bool = False) -> dict[str, Any]:
        """总结一条（一句话 + 要点）；有缓存先读缓存，force=true 重算。"""
        return _run_action(deps, writer, "summarize_item", {"id": id, "force": force})

    @agent.tool
    def summarize_batch(ctx: RunContext[Deps], ids: list[str],
                        style: str = "brief") -> dict[str, Any]:
        """一次总结多条（≤6），style=brief/outline；没跑完的看 skipped。"""
        return _run_action(deps, writer, "summarize_batch", {"ids": ids, "style": style})

    @agent.tool
    def export_markdown(ctx: RunContext[Deps], ids: list[str], title: str = "",
                        style: str = "brief") -> dict[str, Any]:
        """把几条的总结写成 md 文件（≤8 条），返回路径。撤销=删文件。"""
        return _run_action(deps, writer, "export_markdown",
                           {"ids": ids, "title": title, "style": style})

    return agent


# ---------------------------------------------------------------- 主流程
def _resolve(model: Any, chain: list[dict[str, Any]] | None) -> Any:
    if model is not None:
        return model
    return _models(chain or [])


def _picks_to_rows(deps: Deps, answer: Answer, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pick in answer.picks or []:
        item_id = str(getattr(pick, "id", "") or "")
        if not item_id or item_id in seen:
            continue
        row = deps.rows.get(item_id) or deps.store.get_item(item_id)
        if row is None:
            continue
        seen.add(item_id)
        row = dict(row)
        row["why"] = str(getattr(pick, "why", "") or "")
        out.append(row)
        if len(out) >= max(1, limit):
            break
    return out


def _hydrate(deps: Deps, rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """动作返回的是给模型的紧凑行；前端卡片要完整行（封面/链接/reasons），按 id 回库补全。"""
    out: list[dict[str, Any]] = []
    for row in rows[:max(1, limit)]:
        item_id = str(row.get("id") or "")
        full = deps.store.get_item(item_id) if item_id else None
        full = dict(full or row)
        if not full.get("reasons"):
            try:
                full["reasons"] = list(smart.reason_for(full, {}))[:3]
            except Exception:
                full["reasons"] = []
        if row.get("why"):
            full["why"] = row["why"]
        out.append(full)
    return out


def _final_items(deps: Deps, picks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if picks:
        return _hydrate(deps, picks, limit)
    # 模型没挑（超时 / 预算用尽 / 答非所问）：把看过的条目按热度兜底给出去
    rows = sorted(deps.rows.values(),
                  key=lambda r: -int(r.get("engage_score") or r.get("like_count") or 0))
    return _hydrate(deps, rows, limit)


def _fallback(store: Any, message: str, history: list[dict[str, str]] | None,
              limit: int, exclude: list[str] | None) -> dict[str, Any]:
    from . import ai as ai_mod
    try:
        return ai_mod.chat(store, message, history=history, limit=limit, exclude=exclude)
    except Exception as exc:  # 连旧路径都挂了：给一句人话，别抛 500
        return {"engine": "rules", "reply": f"模型和本地兜底都没跑成（{exc}）。",
                "items": [], "count": 0, "suggestions": [], "understood": "",
                "plan": {"mode": "find"}, "provider": ""}


def run(store: Any, message: str, history: list[dict[str, str]] | None = None,
        limit: int = 12, exclude: list[str] | None = None,
        chain: list[dict[str, Any]] | None = None, model: Any = None,
        max_tools: int = MAX_TOOL_CALLS, timeout: float = MAX_SECONDS,
        runner: Any = None, thread_id: str = "", max_steps: int = MAX_STEPS,
        _state: RunState | None = None) -> dict[str, Any]:
    """同步跑一轮（测试与简报用）；API 走 start() 起线程。"""
    prepared = _state is not None
    state = _state or RunState(run_id=uuid.uuid4().hex[:16],
                               thread_id=thread_id or uuid.uuid4().hex[:12])
    with _STATES_LOCK:
        _STATES.setdefault(state.run_id, state)
    writer = EventWriter(store, state)
    started = time.time()
    model_name = ""
    try:
        built = _resolve(model, chain)
        model_name = str(getattr(built, "model_name", "") or (chain or [{}])[0].get("model", ""))
    except Exception:
        built = None
    if not prepared:
        store.start_agent_run(state.run_id, state.thread_id, message, model_name)
        writer.emit("run_start", "run_start",
                    {"run_id": state.run_id, "input": message, "model": model_name})
    deps = Deps(ctx=act_mod.Ctx(store=store, run_id=state.run_id, thread_id=state.thread_id,
                                runner=runner,
                                exports_dir=Path(store.path).parent / act_mod.EXPORT_DIR_NAME),
                store=store, limit=max(1, int(limit)), exclude=tuple(exclude or ()))
    deps.max_tool_calls = max(1, min(int(max_tools), 20))
    deps.ctx.emit = writer.emit
    deps.deadline = started + float(timeout)
    answer: Answer | None = None
    error_text = ""
    try:
        if built is None:
            raise RuntimeError("没有可用的模型")
        agent = build_agent(built, deps, writer, deps.max_tool_calls)
        prompt = message + ("\n\n" + _previous(history) if history else "")
        prompt += _hints(message)
        if exclude:
            prompt += f"\n\n（这些 id 用户已经表示不感兴趣，不要再给：{', '.join(exclude[:20])}）"
        writer.emit("step", "think", {"title": "理解指令", "kind": "think",
                                      "detail": message[:200]})
        result = _with_timeout(
            lambda: agent.run_sync(prompt, deps=deps, message_history=_messages(history)),
            timeout)
        output = getattr(result, "output", None)
        if isinstance(output, Answer):
            answer = output
        usage = getattr(result, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"[:300]
        tokens = 0
    ms = int((time.time() - started) * 1000)

    if answer is None:
        # 模型失败 / 超时 / 预算用尽：用看过的条目兜底，并说明发生了什么
        items = _final_items(deps, [], deps.limit)
        reason = "超时" if "Timeout" in error_text or "超" in error_text else "模型没答完"
        reply = (f"{reason}，先给你我翻到的 {len(items)} 条。" if items
                 else "这轮没跑完，库里也没翻到合适的；换个说法再试？")
        writer.emit("error", "error", {"message": error_text or reason, "fallback": "llm"})
        if deps.budget_hit:
            writer.emit("step", "budget", {"title": "预算用尽，先给你已完成的部分",
                                           "kind": "note"})
    else:
        items = _final_items(deps, _picks_to_rows(deps, answer, deps.limit), deps.limit)
        reply = str(answer.reply or "").strip()[:200] or f"翻到 {len(items)} 条。"

    plan = _plan(deps)
    understood = _understood(deps, items)
    suggestions = _suggestions(items)
    provider = (chain or [{}])[0].get("name", "")
    if reply:
        writer.emit("delta", "delta", {"text": reply})
    # done 带齐渲染所需的一切：前端不必再补一次请求，回放与实时也是同一份
    writer.emit("done", "done", {"reply": reply, "items": items, "plan": plan,
                                 "suggestions": suggestions, "understood": understood,
                                 "provider": provider, "actions": deps.applied,
                                 "usage": {"steps": deps.calls, "ms": ms,
                                           "tokens": tokens}})
    status = "done" if answer is not None else "error"
    store.finish_agent_run(state.run_id, status, reply=reply, error=error_text,
                           steps=deps.calls, ms=ms, tokens=tokens)
    with _STATES_LOCK:
        _STATES.pop(state.run_id, None)
    return {"run_id": state.run_id, "thread_id": state.thread_id, "engine": "agent",
            "provider": provider, "plan": plan, "reply": reply,
            "items": items, "count": len(items), "suggestions": suggestions,
            "understood": understood, "steps": deps.calls, "ms": ms, "tokens": tokens,
            "actions": deps.applied, "error": error_text}


def start(store: Any, message: str, history: list[dict[str, str]] | None = None,
          limit: int = 12, exclude: list[str] | None = None,
          chain: list[dict[str, Any]] | None = None, model: Any = None,
          max_tools: int = MAX_TOOL_CALLS, timeout: float = MAX_SECONDS,
          runner: Any = None, thread_id: str = "") -> dict[str, Any]:
    """起一轮运行并立刻返回 run_id（AC-4：run_start 先落库再返回）。"""
    state = RunState(run_id=uuid.uuid4().hex[:16],
                     thread_id=thread_id or uuid.uuid4().hex[:12])
    with _STATES_LOCK:
        _STATES[state.run_id] = state
    model_name = ""
    try:
        model_name = str(getattr(_resolve(model, chain), "model_name", "") or
                         (chain or [{}])[0].get("model", ""))
    except Exception:
        pass
    store.start_agent_run(state.run_id, state.thread_id, message, model_name)
    EventWriter(store, state).emit("run_start", "run_start",
                                   {"run_id": state.run_id, "input": message,
                                    "model": model_name})

    def work() -> None:
        try:
            run(store, message, history=history, limit=limit, exclude=exclude,
                chain=chain, model=model, max_tools=max_tools, timeout=timeout,
                runner=runner, thread_id=state.thread_id, _state=state)
        except Exception as exc:  # 线程里别静默死掉
            try:
                store.finish_agent_run(state.run_id, "error", reply="",
                                       error=f"{type(exc).__name__}: {exc}"[:300])
                EventWriter(store, state).emit("error", "error",
                                               {"message": str(exc)[:300], "fallback": "llm"})
            except Exception:
                pass
            with _STATES_LOCK:
                _STATES.pop(state.run_id, None)

    threading.Thread(target=work, name=f"agent-{state.run_id}", daemon=True).start()
    return {"run_id": state.run_id, "thread_id": state.thread_id, "status": "running"}


def _hints(message: str) -> str:
    """把规则层读出来的条件提给模型，免得「今天」被它忽略、结果滑成全部。"""
    try:
        parsed = smart.parse_query(message)
    except Exception:
        return ""
    bits: list[str] = []
    labels = smart.PLATFORM_LABELS
    if parsed.get("platforms"):
        bits.append("平台 " + "、".join(labels.get(p, p) for p in parsed["platforms"]))
    if parsed.get("since"):
        bits.append("时间今天（检索时传 since=today）")
    if parsed.get("keyword"):
        bits.append(f"关键词「{parsed['keyword']}」")
    if not bits:
        return ""
    return "\n\n（系统从这句话里读到的条件，仅供参考，请用工具参数落实：" + "；".join(bits) + "）"


# ---------------------------------------------------------------- 给前端的小结
def _plan(deps: Deps) -> dict[str, Any]:
    query = deps.query or {}
    return {"mode": "agent", "platforms": query.get("platforms") or [],
            "kinds": query.get("kinds") or [],
            # 检索时真实生效的起始时间；0 表示模型没加时间限制
            "since": int(query.get("since") or 0),
            # 前端「用这个条件刷」走旧 LIKE（单子串），给第一个词就行；
            # 拼一串会用整串去 LIKE，必然 0 条
            "keyword": (query.get("terms") or [""])[0][:24],
            "sort": query.get("sort") or "freshness"}


def _understood(deps: Deps, items: list[dict[str, Any]]) -> str:
    bits = ["Agent 执行"]
    query = deps.query or {}
    plats = query.get("platforms") or []
    if plats:
        bits.append("、".join(smart_platform_name(p) for p in plats))
    terms = query.get("terms") or []
    if terms:
        bits.append("含「" + "、".join(str(t) for t in terms[:3]) + "」")
    if deps.applied:
        names = {"save_item": "已收藏", "mark_read": "已标记", "ui_filter": "已切筛选"}
        done = [names.get(a["name"], a["name"]) for a in deps.applied]
        bits.append("、".join(dict.fromkeys(done)))
    return " · ".join(bits)


def smart_platform_name(pid: str) -> str:
    return {"bilibili": "B站", "xiaohongshu": "小红书", "douyin": "抖音",
            "juejin": "掘金", "v2ex": "V2EX", "zhihu": "知乎",
            "zhihu-hot": "知乎热榜"}.get(pid, pid)


def _suggestions(items: list[dict[str, Any]]) -> list[str]:
    out = ["只看 B 站", "换成最热的", "只要今天的"]
    if items:
        out.insert(0, "把这几条收藏起来")
    return out[:4]
