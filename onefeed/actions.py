"""动作总线（011 P0）。

为什么不是「让模型生成命令」：后端与前端同机，任意 shell / 任意 HTTP 等于
把本地 RCE 和 SSRF 交给一次幻觉。这里只暴露应用自己的动作白名单：
模型从注册表里选动作、参数被 schema 与 Python 侧双重校验。

级别：
- L0 只读（检索、看单条、同题、统计）
- L1 纯 UI（切筛选、跳页、开详情、提示）——不阻塞，意图进事件流
- L2 写本地（收藏、已读/隐藏）——带 undo_token
- L3 外部副作用（刷新采集）——默认要确认，且同步等到跑完
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import smart
from . import summary as summary_mod

L0, L1, L2, L3 = "L0", "L1", "L2", "L3"

PLATFORM_IDS = ("bilibili", "xiaohongshu", "douyin", "juejin", "v2ex", "zhihu", "zhihu-hot")
PLATFORM_ALIAS = {
    "bilibili": "bilibili", "b站": "bilibili", "哔哩哔哩": "bilibili", "bili": "bilibili",
    "xiaohongshu": "xiaohongshu", "小红书": "xiaohongshu", "xhs": "xiaohongshu", "rednote": "xiaohongshu",
    "douyin": "douyin", "抖音": "douyin", "dy": "douyin",
    "juejin": "juejin", "掘金": "juejin",
    "v2ex": "v2ex",
    "zhihu": "zhihu", "知乎": "zhihu",
    "zhihu-hot": "zhihu-hot", "知乎热榜": "zhihu-hot", "zhihu_hot": "zhihu-hot",
}
SORT_ALIAS = {
    "freshness": "freshness", "fresh": "freshness", "newest": "freshness", "最新": "freshness",
    "最新发布": "freshness", "时间": "freshness",
    "engagement": "engagement", "hot": "engagement", "hottest": "engagement",
    "最热": "engagement", "热门": "engagement", "热度": "engagement", "点赞": "engagement",
    "likes": "engagement", "popular": "engagement",
}
KIND_ALIAS = {
    "video": "video", "视频": "video",
    "article": "article", "文章": "article", "帖子": "article",
    "images": "images", "图文": "images", "图片": "images",
    "short": "short", "动态": "short",
    "list": "list", "榜单": "list",
}


class ActionError(Exception):
    """参数/前置条件不对。消息会原样回给模型，让它改参数重试。"""


class ConfirmRequired(Exception):
    """L3 动作没拿到确认。运行器接住它换成 need_confirm 事件。"""

    def __init__(self, action: str, summary: str, risk: str = ""):
        super().__init__(summary)
        self.action = action
        self.summary = summary
        self.risk = risk


def norm_platforms(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for raw in value:
        key = str(raw or "").strip().lower()
        if not key:
            continue
        pid = PLATFORM_ALIAS.get(key) or PLATFORM_ALIAS.get(key.replace(" ", ""))
        if pid and pid not in out:
            out.append(pid)
    return out


def norm_kinds(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for raw in value:
        kind = KIND_ALIAS.get(str(raw or "").strip().lower())
        if kind and kind not in out:
            out.append(kind)
    return out


def norm_sort(value: Any) -> str:
    return SORT_ALIAS.get(str(value or "").strip().lower(), "freshness")


def since_ts(value: Any, now: float | None = None) -> int:
    """'today' / 'week' / 秒级时间戳 → 起始时间戳。"""
    if value in (None, "", 0, "any", "all"):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    now = time.time() if now is None else now
    if text in ("today", "day", "1d", "今天", "近一天"):
        return int(now - 86400)
    if text in ("week", "7d", "本周", "近一周", "这周"):
        return int(now - 7 * 86400)
    if text in ("month", "30d", "近一月", "这个月"):
        return int(now - 30 * 86400)
    return 0


@dataclass
class Ctx:
    """一次 run 的执行上下文。动作只依赖它，不依赖 FastAPI。"""
    store: Any
    run_id: str = ""
    thread_id: str = ""
    emit: Callable[[str, str, dict[str, Any], str], None] | None = None
    confirmed: set[str] = field(default_factory=set)   # 本次 run 已确认的动作名
    runner: Any = None
    exports_dir: Path | None = None
    refresh_timeout: float = 75.0

    def send(self, kind: str, name: str, payload: dict[str, Any], undo_token: str = "") -> None:
        if self.emit is not None:
            self.emit(kind, name, payload, undo_token)


@dataclass
class Action:
    name: str
    level: str
    summary: str
    params: dict[str, dict[str, Any]]
    run: Callable[..., dict[str, Any]]


REGISTRY: dict[str, Action] = {}


def action(name: str, level: str, summary: str, params: dict[str, dict[str, Any]]):
    def deco(fn: Callable[..., dict[str, Any]]):
        REGISTRY[name] = Action(name, level, summary, params, fn)
        return fn
    return deco


def _p(type_: str, desc: str, **extra: Any) -> dict[str, Any]:
    return {"type": type_, "desc": desc, **extra}


# 两个不进 REGISTRY 的「对话动作」：它们不碰数据，只跟用户打交道。
# 放在运行器里（要阻塞等待事件），但设置页的「Agent 能做什么」也该看得见。
TALK_ACTIONS = [
    {"name": "set_plan", "level": L1, "summary": "动手前先把打算做几步摊给用户看",
     "params": {"steps": _p("list", "步骤清单，3-5 条短句")}},
    {"name": "ask_user", "level": L1, "summary": "关键条件拿不准时问一句，等用户点选或打字",
     "params": {"question": _p("str", "一句话问题"),
                "options": _p("list", "2-5 个选项，能点就不用打字"),
                "multi": _p("bool", "能不能多选"),
                "allow_free": _p("bool", "允不允许自由输入，默认允许")}},
]


def catalog(level: str | None = None) -> list[dict[str, Any]]:
    out = []
    for act in REGISTRY.values():
        if level and act.level != level:
            continue
        out.append({"name": act.name, "level": act.level, "summary": act.summary,
                    "params": act.params})
    for act in TALK_ACTIONS:
        if level and act["level"] != level:
            continue
        out.append(dict(act))
    return out


def _coerce(value: Any, spec: dict[str, Any], name: str, action_name: str) -> Any:
    type_ = spec.get("type")
    if value is None:
        return None
    if type_ == "int":
        try:
            out = int(value)
        except (TypeError, ValueError):
            raise ActionError(f"{action_name}: 参数 {name} 要整数，收到 {value!r}")
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None:
            out = max(int(lo), out)
        if hi is not None:
            out = min(int(hi), out)
        return out
    if type_ == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "是")
        return bool(value)
    if type_ == "list":
        if isinstance(value, (str, int)):
            value = [value]
        if not isinstance(value, (list, tuple)):
            raise ActionError(f"{action_name}: 参数 {name} 要数组")
        return list(value)
    if isinstance(value, (list, dict)):
        return value
    return str(value)


def call(ctx: Ctx, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """校验 → 分级 → 执行。模型拿到的就是返回的那个 dict。"""
    act = REGISTRY.get(name)
    if act is None:
        raise ActionError(f"没有这个动作：{name}")
    args = dict(args or {})
    clean: dict[str, Any] = {}
    for key, value in args.items():
        spec = act.params.get(key)
        if spec is None:
            continue  # 模型多给字段就当没给：严格报错会让它反复重试
        clean[key] = _coerce(value, spec, key, name)
    if act.level == L3 and name not in ctx.confirmed:
        raise ConfirmRequired(name, act.summary, "会打外网、可能触发平台风控")
    started = time.time()
    result = act.run(ctx, **clean)
    if not isinstance(result, dict):
        result = {"ok": True, "value": result}
    result.setdefault("ok", True)
    result["_ms"] = int((time.time() - started) * 1000)
    return result


# ---------------------------------------------------------------- L0 只读
@action("search_items", L0, "在本地库检索条目。多词是「或」，标题命中权重更高。",
        {"terms": _p("list", "关键词数组，1-6 个；空数组=按排序取候选"),
         "platforms": _p("list", "平台 id 或中文名，如 bilibili / B站"),
         "kinds": _p("list", "类型：video/article/images/short/list"),
         "since": _p("str", "today/week，或秒级时间戳；不填=不限"),
         "sort": _p("str", "freshness（最新）或 engagement（最热）"),
         "limit": _p("int", "条数，默认 10，上限 30", min=1, max=30),
         "duration_min_sec": _p("int", "最短时长，单位秒", min=0),
         "duration_max_sec": _p("int", "最长时长，单位秒（10 分钟=600）", min=0),
         "like_min": _p("int", "最低点赞数", min=0)})
def act_search_items(ctx: Ctx, terms=None, platforms=None, kinds=None, since=None,
                     sort="freshness", limit=10, duration_min_sec=None,
                     duration_max_sec=None, like_min=None) -> dict[str, Any]:
    terms = [str(t).strip() for t in (terms or []) if str(t or "").strip()][:6]
    since_value = since_ts(since) or None
    rows = ctx.store.search_items(
        terms=terms or None, platforms=norm_platforms(platforms) or None,
        sort=norm_sort(sort), limit=int(limit or 10), since=since_value,
        duration_min=duration_min_sec, duration_max=duration_max_sec, like_min=like_min)
    wanted = norm_kinds(kinds)
    if wanted:
        rows = [r for r in rows if r.get("kind") in wanted]
    return {"items": [_brief(r) for r in rows], "count": len(rows),
            "query": {"terms": terms, "platforms": norm_platforms(platforms),
                      "kinds": wanted, "sort": norm_sort(sort),
                      # 实际生效的起始时间（秒），plan 原样透传给前端，别让「今天」滑成「全部」
                      "since": int(since_value or 0)}}


@action("get_item", L0, "看单条的完整信息（正文截 600 字）。",
        {"id": _p("str", "条目 id，必须来自检索结果")})
def act_get_item(ctx: Ctx, id: str = "") -> dict[str, Any]:
    row = ctx.store.get_item(str(id or ""))
    if row is None:
        return {"ok": False, "error": f"没有这个 id：{id}。先用 search_items 找。"}
    data = _brief(row)
    data["text"] = str(row.get("text") or "")[:600]
    data["url"] = row.get("url") or ""
    data["published_at"] = int(row.get("published_at") or 0)
    return data


@action("similar_items", L0, "同一条新闻在其它平台的说法（按 cluster_id）。",
        {"id": _p("str", "参照条目 id"), "limit": _p("int", "条数", min=1, max=10)})
def act_similar_items(ctx: Ctx, id: str = "", limit: int = 4) -> dict[str, Any]:
    row = ctx.store.get_item(str(id or ""))
    if row is None:
        return {"ok": False, "error": f"没有这个 id：{id}"}
    cluster = str(row.get("cluster_id") or "")
    if not cluster:
        return {"items": [], "count": 0, "note": "这条没有同题聚合"}
    rows = ctx.store.cluster_items(cluster, exclude_id=str(id), limit=int(limit or 4))
    return {"items": [_brief(r) for r in rows], "count": len(rows), "cluster_id": cluster}


@action("feed_stats", L0, "本地库的规模与平台分布。",
        {"platform": _p("str", "只看某个平台的条数")})
def act_feed_stats(ctx: Ctx, platform: str = "") -> dict[str, Any]:
    pid = (norm_platforms([platform]) or [""])[0] if platform else ""
    out: dict[str, Any] = {"total": ctx.store.count(pid or None), "platforms": []}
    for row in ctx.store.platforms():
        out["platforms"].append({"platform": row["platform"], "count": row["count"]})
    if not pid:
        try:
            out["summary"] = smart.summary(ctx.store)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- L1 纯 UI
def _ui(ctx: Ctx, kind: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    ctx.send("action", name, {"kind": kind, "payload": payload})
    return {"ok": True, "ui": kind, "payload": payload}


@action("ui_filter", L1, "切 feed 的筛选条件（平台/排序/时间/关键词/类型）。",
        {"platforms": _p("list", "平台列表，空数组=全部"),
         "sort": _p("str", "freshness 或 engagement"),
         "since": _p("str", "today/week"),
         "keyword": _p("str", "关键词，空=清掉"),
         "kinds": _p("list", "类型过滤")})
def act_ui_filter(ctx: Ctx, platforms=None, sort=None, since=None, keyword=None,
                  kinds=None) -> dict[str, Any]:
    payload = {"platforms": norm_platforms(platforms), "sort": norm_sort(sort or "freshness"),
               "since": str(since or ""), "keyword": str(keyword or ""),
               "kinds": norm_kinds(kinds)}
    return _ui(ctx, "ui_filter", "ui_filter", payload)


@action("ui_navigate", L1, "跳到某个页面。",
        {"page": _p("str", "feed / item / settings / market / saved"),
         "id": _p("str", "page=item 时的条目 id")})
def act_ui_navigate(ctx: Ctx, page: str = "feed", id: str = "") -> dict[str, Any]:
    allowed = {"feed", "item", "settings", "market", "saved"}
    target = str(page or "feed").strip().lower()
    if target not in allowed:
        raise ActionError(f"ui_navigate: 只能去 {sorted(allowed)}")
    payload = {"page": target}
    if id:
        payload["id"] = str(id)
    return _ui(ctx, "ui_navigate", "ui_navigate", payload)


@action("ui_open_item", L1, "在前端打开某条的详情抽屉。", {"id": _p("str", "条目 id")})
def act_ui_open_item(ctx: Ctx, id: str = "") -> dict[str, Any]:
    if not str(id or "").strip():
        raise ActionError("ui_open_item: 缺 id")
    return _ui(ctx, "ui_open_item", "ui_open_item", {"id": str(id)})


@action("ui_toast", L1, "给用户一条即时提示。",
        {"text": _p("str", "提示文字，≤80 字"), "level": _p("str", "info / success / warn")})
def act_ui_toast(ctx: Ctx, text: str = "", level: str = "info") -> dict[str, Any]:
    lv = str(level or "info").lower()
    return _ui(ctx, "ui_toast", "ui_toast",
               {"text": str(text or "")[:80], "level": lv if lv in ("info", "success", "warn") else "info"})


# ---------------------------------------------------------------- L2 写本地
def _undo_token(kind: str, **fields: Any) -> str:
    return json.dumps({"kind": kind, **fields}, ensure_ascii=False)


@action("save_item", L2, "收藏/取消收藏一条（落库，刷新还在）。",
        {"id": _p("str", "条目 id"), "on": _p("bool", "true=收藏，false=取消，不填=true")})
def act_save_item(ctx: Ctx, id: str = "", on=True) -> dict[str, Any]:
    item_id = str(id or "").strip()
    if not item_id:
        raise ActionError("save_item: 缺 id")
    if ctx.store.get_item(item_id) is None:
        return {"ok": False, "error": f"库里没有 {item_id}，先检索到再收藏"}
    before = ctx.store.get_mark(item_id)
    after = ctx.store.mark_item(item_id, saved=bool(on))
    token = _undo_token("mark", id=item_id, saved=before["saved"])
    payload = {"id": item_id, "saved": after["saved"], "title": _title(ctx, item_id)}
    ctx.send("action", "save_item", payload, token)
    return {"ok": True, "saved": after["saved"], "id": item_id}


@action("mark_read", L2, "标已读 / 不感兴趣（hidden=1 之后不再进 feed）。",
        {"ids": _p("list", "条目 id 数组"), "state": _p("str", "read / unread / hide / unhide")})
def act_mark_read(ctx: Ctx, ids=None, state: str = "read") -> dict[str, Any]:
    wanted = [str(x) for x in (ids or []) if str(x or "").strip()][:50]
    if not wanted:
        raise ActionError("mark_read: ids 为空")
    mode = str(state or "read").strip().lower()
    if mode not in ("read", "unread", "hide", "unhide"):
        raise ActionError("mark_read: state 只能是 read/unread/hide/unhide")
    changed = []
    for item_id in wanted:
        if mode in ("read", "unread"):
            after = ctx.store.mark_item(item_id, read=(mode == "read"))
            changed.append({"id": item_id, "read": after["read"]})
        else:
            after = ctx.store.mark_item(item_id, hidden=(mode == "hide"))
            changed.append({"id": item_id, "hidden": after["hidden"]})
    token = _undo_token("marks", ids=wanted, state=mode)
    ctx.send("action", "mark_read", {"state": mode, "items": changed}, token)
    return {"ok": True, "state": mode, "changed": changed}


# ---------------------------------------------------------------- L3 外部副作用
def pull_feed(ctx: Ctx, platforms=None, timeout: float | None = None,
              announce: bool = True,
              should_stop: Callable[[], bool] | None = None) -> dict[str, Any]:
    """抓一轮并同步等到跑完；用户点刷新与 Agent 自动兜底共用这一条路。

    L3 确认在 call() 里，不在这个函数里：Agent 自动兜底绕开的是「等用户点允许」，
    不是平台冷却。抓太密会被平台返回空列表，看起来像「今天没内容」，比抓不到更糟。
    """
    runner = ctx.runner
    if runner is None:
        return {"ok": False, "error": "刷新组件不在，无法采集"}
    pids = norm_platforms(platforms) or None
    before = ctx.store.count()
    started, snapshot = runner.trigger(platforms=pids)
    snapshot = snapshot or {}
    if not started and not snapshot.get("running"):
        # 没起新的一轮、也没有正在跑的：冷却挡完了 / 没有插件。原样把原因交回去。
        return {"ok": False,
                "error": str(snapshot.get("error") or "已经有一轮刷新在跑"),
                "progress": snapshot}
    budget = float(ctx.refresh_timeout if timeout is None else timeout)
    deadline = time.time() + max(5.0, budget)
    while time.time() < deadline:
        if should_stop is not None and should_stop():
            return {"ok": False, "error": "已停止", "stopped": True,
                    "progress": runner.snapshot() if hasattr(runner, "snapshot") else {}}
        # 已经在跑（自己起的，或用户手点的那一轮）都跟着等，不另起
        if not runner.running():
            break
        time.sleep(0.5)
    snap = runner.snapshot() if hasattr(runner, "snapshot") else {}
    added = ctx.store.count() - before
    if announce:
        ctx.send("step", "refresh_feed",
                 {"title": f"刷新完成，新增 {added} 条", "detail": snap})
    return {"ok": True, "added": added, "progress": snap,
            "timed_out": bool(snap.get("running"))}


@action("refresh_feed", L3, "触发一次采集刷新，并等它跑完（可能几十秒）。",
        {"platforms": _p("list", "只刷这些平台，空=全部")})
def act_refresh_feed(ctx: Ctx, platforms=None) -> dict[str, Any]:
    return pull_feed(ctx, platforms)


# ---------------------------------------------------------------- L2 长任务
# 总结与导出都要等模型（单个 provider 最多 20 秒），一次批量很容易吃掉整轮 90s。
# 所以这里给「一次动作」自己的预算：到点就把没跑完的列进 skipped，不假装成功。
SUMMARY_STYLES = ("brief", "outline")
BATCH_MAX = 6
EXPORT_MAX = 8
EXPORT_DIR_NAME = "exports"
TASK_BUDGET = 55.0


def _style(value: Any) -> str:
    mode = str(value or "brief").strip().lower()
    return mode if mode in SUMMARY_STYLES else "brief"


def _budget(value: Any) -> float:
    try:
        seconds = float(value or TASK_BUDGET)
    except (TypeError, ValueError):
        seconds = TASK_BUDGET
    return max(5.0, min(70.0, seconds))


def _host(ctx: Ctx) -> Any:
    """插件宿主：有就用它拿字幕/平台总结，没有 summary.build 会退到详情正文。"""
    return getattr(ctx.runner, "host", None)


def _summarize(ctx: Ctx, item_id: str, force: bool = False) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """返回 (条目, 总结 payload, 是否命中缓存)。缓存策略与 /item/{id}/summary 一致。"""
    row = ctx.store.get_item(item_id)
    if row is None:
        raise ActionError(f"库里没有这个 id：{item_id}")
    level = summary_mod.configured_depth()
    if not force:
        cached = ctx.store.get_summary(item_id, level)
        payload = cached.get("payload") if isinstance(cached, dict) else None
        if isinstance(payload, dict) and payload.get("tldr") is not None:
            return row, payload, True
    try:
        payload = summary_mod.build(ctx.store, _host(ctx), row, level)
    except Exception as exc:  # noqa: BLE001 - 正文为空/模型全挂都归成一句话
        raise ActionError(str(exc)[:160] or "总结失败") from exc
    ctx.store.save_summary(item_id, payload, level)
    return row, payload, False


def _pack_summary(row: dict[str, Any], payload: dict[str, Any], cached: bool) -> dict[str, Any]:
    points = []
    for point in (payload.get("points") or [])[:6]:
        if isinstance(point, dict) and str(point.get("text") or "").strip():
            points.append({"t": point.get("t"), "text": str(point["text"])[:120]})
    return {
        "id": row.get("id"),
        "title": str(row.get("title") or "")[:90],
        "platform": row.get("platform"),
        "url": row.get("url") or "",
        "tldr": str(payload.get("tldr") or "")[:200],
        "points": points,
        "caveat": str(payload.get("caveat") or "")[:160],
        "basis": payload.get("basis") or "",
        "cached": bool(cached),
    }


def _slug(title: str) -> str:
    text = re.sub(r'[\\/:*?"<>|\s]+', "-", str(title or "")).strip("-")
    return (text[:40].strip("-") or "brief")


def _exports_root(ctx: Ctx) -> Path:
    root = Path(ctx.exports_dir) if ctx.exports_dir else Path(ctx.store.path).parent / EXPORT_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _render_markdown(title: str, style: str, summaries: list[dict[str, Any]],
                     skipped: list[dict[str, Any]]) -> str:
    lines = [f"# {title}", "", f"> 由 OneFeed 助手生成 · {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for index, item in enumerate(summaries, 1):
        lines.append(f"## {index}. {item['title']}")
        meta = " · ".join(x for x in (item.get("platform") or "", "有缓存" if item.get("cached") else "新总结") if x)
        if meta:
            lines.append(f"*{meta}*")
        if item.get("url"):
            lines.append("")
            lines.append(f"[原链接]({item['url']})")
        if style != "outline" and item.get("tldr"):
            lines.append("")
            lines.append(f"**{item['tldr']}**")
        points = item.get("points") or []
        if points:
            lines.append("")
            for point in points:
                stamp = f"[{_mmss(point['t'])}] " if isinstance(point.get("t"), (int, float)) else ""
                lines.append(f"- {stamp}{point['text']}")
        if item.get("caveat"):
            lines.append("")
            lines.append(f"> {item['caveat']}")
        lines.append("")
    if skipped:
        lines.append("## 没跑完的")
        lines.append("")
        for miss in skipped:
            lines.append(f"- {miss.get('id')}：{miss.get('error')}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_export(ctx: Ctx, title: str, text: str) -> Path:
    root = _exports_root(ctx)
    base = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}"
    path = root / f"{base}.md"
    suffix = 2
    while path.exists():
        path = root / f"{base}-{suffix}.md"
        suffix += 1
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _mmss(sec: Any) -> str:
    try:
        value = max(0, int(float(sec)))
    except (TypeError, ValueError):
        return "00:00"
    return f"{value // 60:02d}:{value % 60:02d}"


@action("summarize_item", L0, "把一条内容总结成「一句话 + 要点」，有缓存先用缓存。",
        {"id": _p("str", "条目 id，必须来自检索结果"),
         "force": _p("bool", "true=忽略缓存重算")})
def act_summarize_item(ctx: Ctx, id: str = "", force=False) -> dict[str, Any]:
    item_id = str(id or "").strip()
    if not item_id:
        raise ActionError("summarize_item: 缺 id")
    row, payload, cached = _summarize(ctx, item_id, bool(force))
    out = _pack_summary(row, payload, cached)
    ctx.send("action", "summarize_item",
             {"id": item_id, "title": out["title"], "cached": cached})
    return out


@action("summarize_batch", L0, "一次总结多条（≤6），到预算还没跑完的列进 skipped。",
        {"ids": _p("list", "条目 id 数组，最多 6 条"),
         "style": _p("str", "brief=一句话+要点；outline=只要要点"),
         "budget_sec": _p("int", "这次最多花多少秒，默认 55", min=5, max=70)})
def act_summarize_batch(ctx: Ctx, ids=None, style: str = "brief", budget_sec=55) -> dict[str, Any]:
    wanted = [str(x).strip() for x in (ids or []) if str(x or "").strip()][:BATCH_MAX]
    if not wanted:
        raise ActionError("summarize_batch: ids 为空")
    mode = _style(style)
    deadline = time.time() + _budget(budget_sec)
    summaries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item_id in wanted:
        if time.time() >= deadline:
            skipped.append({"id": item_id, "error": "时间预算用完了，这条还没跑"})
            continue
        try:
            row, payload, cached = _summarize(ctx, item_id)
        except ActionError as exc:
            skipped.append({"id": item_id, "error": str(exc)})
            continue
        summaries.append(_pack_summary(row, payload, cached))
    ctx.send("action", "summarize_batch",
             {"count": len(summaries), "skipped": len(skipped), "style": mode})
    return {"ok": True, "summaries": summaries, "count": len(summaries),
            "skipped": skipped, "style": mode, "budget_sec": int(_budget(budget_sec))}


@action("export_markdown", L2, "把几条的总结写成一份 Markdown（撤销=删掉这个文件）。",
        {"ids": _p("list", "条目 id 数组，最多 8 条"),
         "title": _p("str", "文件标题，空=按日期起名"),
         "style": _p("str", "brief=一句话+要点；outline=只要要点"),
         "budget_sec": _p("int", "这次最多花多少秒，默认 55", min=5, max=70)})
def act_export_markdown(ctx: Ctx, ids=None, title: str = "", style: str = "brief",
                        budget_sec=55) -> dict[str, Any]:
    wanted = [str(x).strip() for x in (ids or []) if str(x or "").strip()][:EXPORT_MAX]
    if not wanted:
        raise ActionError("export_markdown: ids 为空")
    mode = _style(style)
    heading = str(title or "").strip()[:60] or f"OneFeed 简报 {time.strftime('%Y-%m-%d')}"
    deadline = time.time() + _budget(budget_sec)
    summaries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item_id in wanted:
        if time.time() >= deadline:
            skipped.append({"id": item_id, "error": "时间预算用完了，这条没写进文件"})
            continue
        try:
            row, payload, cached = _summarize(ctx, item_id)
        except ActionError as exc:
            skipped.append({"id": item_id, "error": str(exc)})
            continue
        summaries.append(_pack_summary(row, payload, cached))
    if not summaries:
        raise ActionError("这几次总结都没跑成，文件没生成：" +
                          (skipped[0]["error"] if skipped else "没有可用条目"))
    text = _render_markdown(heading, mode, summaries, skipped)
    path = _write_export(ctx, heading, text)
    token = _undo_token("export", path=str(path))
    ctx.send("action", "export_markdown",
             {"path": str(path), "count": len(summaries), "title": heading}, token)
    return {"ok": True, "path": str(path), "count": len(summaries),
            "bytes": len(text.encode("utf-8")), "skipped": skipped}


# ---------------------------------------------------------------- 撤销
def parse_undo(token: str) -> dict[str, Any]:
    try:
        data = json.loads(token or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def apply_undo(store: Any, token: str) -> dict[str, Any]:
    data = parse_undo(token)
    kind = data.get("kind")
    if kind == "mark":
        mark = store.mark_item(str(data.get("id") or ""), saved=bool(data.get("saved")))
        return {"ok": True, "mark": mark}
    if kind == "marks":
        ids = [str(x) for x in (data.get("ids") or [])]
        state = str(data.get("state") or "")
        for item_id in ids:
            if state == "read":
                store.mark_item(item_id, read=False)
            elif state == "unread":
                store.mark_item(item_id, read=True)
            elif state == "hide":
                store.mark_item(item_id, hidden=False)
            elif state == "unhide":
                store.mark_item(item_id, hidden=True)
        return {"ok": True, "reverted": ids, "state": state}
    if kind == "export":
        # 只删 exports 目录里自己写出来的 md：token 是前端可伪造的，不能顺着路径乱删
        root = (Path(store.path).parent / EXPORT_DIR_NAME).resolve()
        try:
            target = Path(str(data.get("path") or "")).resolve()
        except (OSError, ValueError):
            return {"ok": False, "error": "撤销路径不对"}
        if target.parent != root or target.suffix.lower() != ".md":
            return {"ok": False, "error": "只能撤销 exports 目录里的 md 文件"}
        if not target.exists():
            return {"ok": True, "deleted": str(target), "note": "文件已经不在"}
        target.unlink()
        return {"ok": True, "deleted": str(target)}
    return {"ok": False, "error": "这个动作不可撤销"}


# ---------------------------------------------------------------- 内部
def _title(ctx: Ctx, item_id: str) -> str:
    row = ctx.store.get_item(item_id)
    return str(row.get("title") or "") if row else ""


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    """给模型看的紧凑条目：字段少、字数可控，省 token。"""
    duration = int(row.get("duration") or 0)
    published = int(row.get("published_at") or 0)
    hours = round((time.time() - published) / 3600, 1) if published else None
    return {
        "id": row.get("id"),
        "platform": row.get("platform"),
        "kind": row.get("kind"),
        "title": str(row.get("title") or "")[:90],
        "author": str(row.get("author") or "")[:20],
        "text": str(row.get("text") or "")[:120],
        "minutes": round(duration / 60) if duration else None,
        "like": int(row.get("like_count") or 0),
        "hours_ago": hours,
        "cluster_id": row.get("cluster_id") or "",
    }
