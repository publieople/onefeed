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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import smart

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


def catalog(level: str | None = None) -> list[dict[str, Any]]:
    out = []
    for act in REGISTRY.values():
        if level and act.level != level:
            continue
        out.append({"name": act.name, "level": act.level, "summary": act.summary,
                    "params": act.params})
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
@action("refresh_feed", L3, "触发一次采集刷新，并等它跑完（可能几十秒）。",
        {"platforms": _p("list", "只刷这些平台，空=全部")})
def act_refresh_feed(ctx: Ctx, platforms=None) -> dict[str, Any]:
    runner = ctx.runner
    if runner is None:
        return {"ok": False, "error": "刷新组件不在，无法采集"}
    pids = norm_platforms(platforms) or None
    before = ctx.store.count()
    started, snapshot = runner.trigger(platforms=pids)
    if not started:
        return {"ok": False, "error": "已经有一轮刷新在跑", "progress": snapshot}
    deadline = time.time() + float(ctx.refresh_timeout)
    while time.time() < deadline:
        if not runner.running():
            break
        time.sleep(0.5)
    snap = runner.snapshot() if hasattr(runner, "snapshot") else {}
    added = ctx.store.count() - before
    ctx.send("step", "refresh_feed", {"title": f"刷新完成，新增 {added} 条", "detail": snap})
    return {"ok": True, "added": added, "progress": snap}


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
