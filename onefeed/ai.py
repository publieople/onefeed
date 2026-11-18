"""AI 助手：把一句话变成检索条件，再替结果编理由。

分工是刻意的——模型只做「理解」和「措辞」，内容永远来自本地库：

- 没配 key：规则解析（smart.parse_query）+ 本地排序。功能完整，断网也能演示。
- 配了 key：模型输出结构化 JSON（平台 / 类型 / 时间 / 关键词 / 排序 / 意图），
  解析失败、超时、模型胡说一律落回规则。现场不赌 WiFi。

所以「AI 帮找视频」的实际执行链是：模型理解 -> 宿主查询本地 SQLite -> 前端渲染，
模型不接触也不编造内容，这是能随口解释「它凭什么这么推荐」的前提。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from . import settings as settings_mod, smart

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
TIMEOUT = 20.0
MAX_HISTORY = 6

PLATFORM_IDS = ("bilibili", "xiaohongshu", "douyin", "juejin", "v2ex", "zhihu", "zhihu-hot")
KINDS = ("video", "images", "article", "short", "list")

SYSTEM_PROMPT = """你是 OneFeed 的找内容助手。用户用一句话说自己想看什么，你把它翻译成检索条件。

只输出 JSON，不要解释，格式：
{"mode":"find|browse","platforms":[],"kinds":[],"since":"today|week|null","keyword":"","sort":"freshness|engagement","reply":"一句中文"}

规则：
- platforms 只能从这些里选：bilibili（B 站）、xiaohongshu（小红书）、douyin（抖音）、juejin（掘金）、v2ex、zhihu（知乎推荐）、zhihu-hot（知乎热榜）。用户没说平台就留空数组（表示全平台）。
- kinds 只能从 video / images / article / short / list 里选，用户没说就留空。
- since：说「今天 / 刚刚 / 最近」用 today，说「这周 / 本周」用 week，没提时间用 null。
- keyword：用户真正想看的主题词，保留原词（如 AI、大模型、量子计算、装机），不要塞平台名和「视频」这类词；没有具体主题就留空字符串。
- sort：用户说「最热 / 火 / 高赞」用 engagement，否则 freshness。
- mode：用户说「随便来点 / 刷一刷 / 换一批 / 无聊」用 browse，否则 find。
- reply：一句 20 字以内的中文，说明你把他的话理解成了什么，不要客套。
"""


# ---------------------------------------------------------------- 配置

def _public(provider: dict[str, Any]) -> dict[str, Any]:
    """对外的模型条目：只报「配没配」和末四位，key 永不出宿主。"""
    key = str(provider.get("key") or "")
    return {
        "id": provider.get("id", ""),
        "name": provider.get("name", ""),
        "base_url": provider.get("base_url", ""),
        "model": provider.get("model", ""),
        "key_set": bool(key),
        "key_hint": ("…" + key[-4:]) if len(key) >= 8 else "",
    }


def _provider_list(conf: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """按顺序排出「这一轮可以试哪些模型」。

    顺序 = 环境变量（临时覆盖）→ 设置里的顺序表 → 旧版单模型字段。
    顺序表里禁用的、没 key 的直接跳过——它们留在设置里但不上场。
    """
    conf = conf if conf is not None else settings_mod.load()
    out: list[dict[str, Any]] = []
    env_key = (os.environ.get("ONEFEED_AI_KEY") or "").strip()
    if env_key:
        out.append({
            "id": "env", "name": "环境变量",
            "base_url": str(conf.get("ai_base_url") or DEFAULT_BASE).rstrip("/"),
            "model": str(conf.get("ai_model") or DEFAULT_MODEL), "key": env_key,
        })
    for item in conf.get("ai_providers") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        base = str(item.get("base_url") or "").rstrip("/")
        model = str(item.get("model") or "").strip()
        if not key or not base or not model or item.get("enabled") is False:
            continue
        out.append({"id": str(item.get("id") or ""), "name": str(item.get("name") or model),
                    "base_url": base, "model": model, "key": key})
    if out:
        return out
    legacy = str(conf.get("ai_api_key") or "").strip()
    if legacy:
        out.append({
            "id": "legacy", "name": "默认模型",
            "base_url": str(conf.get("ai_base_url") or DEFAULT_BASE).rstrip("/"),
            "model": str(conf.get("ai_model") or DEFAULT_MODEL), "key": legacy,
        })
    return out


# 最近一次「谁上场、成没成」——设置页据此显示「上一个模型挂了，正在用第 2 个」。
_LAST: dict[str, Any] = {"at": 0, "provider": "", "ok": False, "error": "", "tried": []}


def _agent_enabled(conf: dict[str, Any] | None = None) -> bool:
    env = (os.environ.get("ONEFEED_AI_AGENT") or "").strip().lower()
    if env in ("0", "false", "off", "no"):
        return False
    conf = conf if conf is not None else settings_mod.load()
    return bool(conf.get("ai_agent", True))


def _agent_available(conf: dict[str, Any] | None = None,
                     chain: list[dict[str, Any]] | None = None) -> bool:
    """agent 能不能上场：开关开着 + 有模型 + 依赖装得上。只查包存不存在，不 import（1.7s）。"""
    if not _agent_enabled(conf):
        return False
    if not (chain if chain is not None else _provider_list(conf)):
        return False
    try:
        from importlib.util import find_spec
        return find_spec("pydantic_ai") is not None
    except (ImportError, ValueError):
        return False


def status() -> dict[str, Any]:
    conf = settings_mod.load()
    chain = _provider_list(conf)
    head = chain[0] if chain else None
    return {
        "engine": "llm" if chain else "rules",
        "agent": _agent_available(conf, chain),
        "model": head["model"] if head else str(conf.get("ai_model") or DEFAULT_MODEL),
        "base_url": head["base_url"] if head else str(conf.get("ai_base_url") or DEFAULT_BASE),
        "configured": bool(chain),
        "active": head["name"] if head else "",
        "providers": [_public(p) for p in chain],
        "last": dict(_LAST),
        "platforms": list(PLATFORM_IDS),
        "kinds": list(KINDS),
    }


def _post(provider: dict[str, Any], messages: list[dict[str, str]],
          max_tokens: int = 300, temperature: float = 0.2) -> str:
    if not provider.get("key"):
        raise RuntimeError("没有配置模型 key")
    body = json.dumps({
        "model": provider["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        str(provider["base_url"]).rstrip("/") + "/chat/completions", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + str(provider["key"])})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str(payload["choices"][0]["message"]["content"])


def _chat(provider: dict[str, Any], messages: list[dict[str, str]]) -> str:
    return _post(provider, messages)


def complete(messages: list[dict[str, str]], max_tokens: int = 900,
             temperature: float = 0.3) -> tuple[str, dict[str, Any]]:
    """要一段长回答（总结用）：按顺序表挨个试，返回原文和命中的那个模型。

    与 plan() 的区别只有一个——失败不会静默降级，由调用方决定退回规则还是报错。
    """
    chain = _provider_list()
    if not chain:
        raise RuntimeError("没有配置模型 key")
    tried: list[str] = []
    for provider in chain:
        tried.append(provider["name"])
        try:
            raw = _post(provider, messages, max_tokens=max_tokens, temperature=temperature)
            _LAST.update({"at": int(time.time()), "provider": provider["name"],
                          "ok": True, "error": "", "tried": tried})
            return raw, provider
        except Exception as exc:  # noqa: BLE001 - 任何一个挂了就换下一个
            _LAST.update({"at": int(time.time()), "provider": provider["name"],
                          "ok": False, "error": (str(exc) or exc.__class__.__name__)[:200],
                          "tried": list(tried)})
    raise RuntimeError("、".join(tried) + " 都不可用")


def test_provider(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """给设置页的「测一下」按钮用：只发一句最小请求，确认这个模型通不通。"""
    raw = raw if isinstance(raw, dict) else {}
    stored = {str(p.get("id")): p for p in settings_mod.load().get("ai_providers") or []
              if isinstance(p, dict)}
    target: dict[str, Any] | None = None
    if raw.get("base_url") and raw.get("model"):
        target = {
            "id": str(raw.get("id") or "draft"),
            "name": str(raw.get("name") or raw.get("model")),
            "base_url": str(raw["base_url"]).rstrip("/"),
            "model": str(raw["model"]),
            "key": str(raw.get("key") or stored.get(str(raw.get("id")), {}).get("key") or "").strip(),
        }
    else:
        wanted = str(raw.get("id") or "").strip()
        chain = _provider_list()
        target = next((p for p in chain if p["id"] == wanted), None) if wanted else None
        target = target or (chain[0] if chain else None)
    if not target:
        return {"ok": False, "error": "还没有可用的模型配置"}
    started = time.time()
    try:
        reply = _chat(target, [{"role": "user",
                                "content": "只回一个 JSON：{\"reply\":\"在线\"}"}])
        return {"ok": True, "ms": int((time.time() - started) * 1000),
                "provider": target["name"], "model": target["model"], "reply": reply[:160]}
    except Exception as exc:  # noqa: BLE001 - 设置页只需要一句话原因
        return {"ok": False, "ms": int((time.time() - started) * 1000),
                "provider": target["name"], "model": target["model"],
                "error": (str(exc) or exc.__class__.__name__)[:300]}


# ---------------------------------------------------------------- 解析

def _clean_platforms(raw: Any) -> list[str]:
    out: list[str] = []
    for value in raw if isinstance(raw, list) else []:
        pid = str(value or "").strip()
        if pid in PLATFORM_IDS and pid not in out:
            out.append(pid)
    return out


def _clean_kinds(raw: Any) -> list[str]:
    out: list[str] = []
    for value in raw if isinstance(raw, list) else []:
        kind = str(value or "").strip()
        if kind in KINDS and kind not in out:
            out.append(kind)
    return out


def _accept(obj: dict[str, Any], message: str) -> dict[str, Any]:
    """把模型给的 JSON 收紧成宿主认识的结构；字段不可信就丢掉。"""
    since_word = str(obj.get("since") or "").strip().lower()
    since = None
    if since_word == "today":
        now = int(time.time())
        since = now - (now % 86400) - 8 * 3600
    elif since_word == "week":
        since = int(time.time()) - 6 * 86400
    sort = "engagement" if str(obj.get("sort") or "").strip() == "engagement" else "freshness"
    mode = "browse" if str(obj.get("mode") or "").strip() == "browse" else "find"
    keyword = str(obj.get("keyword") or "").strip()[:40]
    return {
        "mode": mode,
        "platforms": _clean_platforms(obj.get("platforms")),
        "kinds": _clean_kinds(obj.get("kinds")),
        "since": since,
        "keyword": keyword,
        "sort": sort,
        "reply": str(obj.get("reply") or "").strip()[:60],
        "engine": "llm",
        "raw": message,
    }


_STOP_TOKENS = {
    "把", "帮", "帮我", "给我", "找", "找找", "找一下", "找出来", "出来", "一下", "下",
    "在", "聊", "聊聊", "在聊", "关于", "推荐", "看看", "看一看", "搜", "搜一下",
    "最近", "近期", "这几天", "这周", "本周", "今天", "昨天", "刚才",
    "内容", "东西", "视频", "文章", "图文", "动态", "榜单", "帖子",
    "的", "了", "吧", "呢", "啊", "吗", "嘛", "呀", "和", "跟", "与",
}

# 只调整条件、不换主题的说法。「换成最热的」「只要今天的」都算——它们本身不含主题词，
# 机械地按字面解析会得到一个空条件，然后退化成全库乱搜。
_REFINE_NOISE = re.compile(
    r"换成|换一批|换一个|换个|再来|再点|只要|只看|只看|看看|来点|更多|一下|"
    r"最热|热门|最新|新鲜|今天|昨天|这周|本周|最近|"
    r"内容|视频|图文|文章|动态|榜单|排序|"
    r"给我|帮我|都|全|也|就|再|还|的|了|吧|呢|啊|个|条|点"
)


def _is_refine(message: str) -> bool:
    return not _REFINE_NOISE.sub("", message).strip()


def _previous_plan(history: list[dict[str, str]] | None) -> dict[str, Any] | None:
    """从历史里捞上一轮的检索计划：前端会把它挂在 assistant 那条上。"""
    for turn in reversed(history or []):
        raw = turn.get("plan")
        if isinstance(raw, dict) and (raw.get("platforms") or raw.get("keyword") or raw.get("mode")):
            return {
                "mode": "browse" if raw.get("mode") == "browse" else "find",
                "platforms": [p for p in raw.get("platforms") or [] if p in PLATFORM_IDS],
                "kinds": [k for k in raw.get("kinds") or [] if k in KINDS],
                "since": raw.get("since") if isinstance(raw.get("since"), int) else None,
                "keyword": str(raw.get("keyword") or "")[:40],
                "sort": "engagement" if raw.get("sort") == "engagement" else "freshness",
            }
    return None


def _rule_plan(message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    parsed = smart.parse_query(message)
    lowered = message.lower()
    mode = "browse" if re.search(r"随便|换一批|无聊|刷刷|刷一刷|来点|换着|别老|都来点|随机", lowered) else "find"
    # parse_query 不懂「随便来点」「别老是同一个平台」这种玩法，关键词会被语气词污染，这里再洗一遍
    keyword = parsed["keyword"]
    for noise in ("随便", "来点", "换一批", "无聊", "刷刷", "刷一刷", "看看",
                  "有什么", "有没有", "有啥", "哪些", "什么"):
        keyword = keyword.replace(noise, " ")
    keyword = re.sub(r"别老是?[^，。！？\s]*?平台[^，。！？\s]*|同一个平台|换着来?|都来点|随机", " ", keyword)
    keyword = " ".join(keyword.split())
    # 功能词会以「把最近」这种粘连形式进来，先按子串拆掉多字词，再逐词筛，
    # 否则每句话都被加一个假主题，结果必然 0 条。
    for word in sorted((w for w in _STOP_TOKENS if len(w) > 1), key=len, reverse=True):
        keyword = keyword.replace(word, " ")
    keyword = " ".join(t for t in keyword.split() if t not in _STOP_TOKENS)[:40]
    out = {
        "mode": mode,
        "platforms": parsed["platforms"],
        "kinds": parsed["kinds"],
        "since": parsed["since"],
        "keyword": keyword,
        "sort": "engagement" if re.search(r"最热|热门|火|高赞|爆", lowered) else "freshness",
        "reply": "",
        "engine": "rules",
        "provider": "",
        "raw": message,
    }

    # 追问（「换成最热的」「只要今天的」「再看看」）本身不带主题，条件要接着上一轮，否则会退化成全库乱搜。
    prev = _previous_plan(history)
    if prev:
        refine_only = _is_refine(message) or (
            not out["platforms"] and not out["keyword"] and out["since"] is None)
        if refine_only:
            out["platforms"] = prev["platforms"]
            out["kinds"] = out["kinds"] or prev["kinds"]
            out["keyword"] = prev["keyword"]
            out["since"] = prev["since"]
            out["mode"] = out["mode"] if out["mode"] == "browse" else prev["mode"]
        else:
            out["platforms"] = out["platforms"] or prev["platforms"]
            if out["since"] is None:
                out["since"] = prev["since"]
    return out


def plan(message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """一句话 -> 检索计划。模型不可用时静默落回规则，绝不把错误抛给用户。"""
    message = (message or "").strip()[:200]
    if not message:
        return _rule_plan("")
    chain = _provider_list()
    fallback = _rule_plan(message, history)
    if not chain:
        return fallback
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-MAX_HISTORY:]:
        role = "user" if turn.get("role") == "user" else "assistant"
        content = str(turn.get("text") or turn.get("content") or "")[:200]
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    tried: list[str] = []
    for provider in chain:
        tried.append(provider["name"])
        try:
            raw = _chat(provider, messages)
            match = re.search(r"\{.*\}", raw, re.S)
            obj = json.loads(match.group(0) if match else raw)
            if isinstance(obj, dict):
                plan = _accept(obj, message)
                plan["provider"] = provider["name"]
                _LAST.update({"at": int(time.time()), "provider": provider["name"],
                              "ok": True, "error": "", "tried": tried})
                return plan
            raise ValueError("模型没给 JSON 对象")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, RuntimeError) as exc:
            # 这个模型挂了就换下一个：超时、额度用光、模型下线都走同一条路。
            _LAST.update({"at": int(time.time()), "provider": provider["name"],
                          "ok": False, "error": (str(exc) or exc.__class__.__name__)[:200],
                          "tried": list(tried)})
    return fallback


# ---------------------------------------------------------------- 检索与说法

def _label(pid: str) -> str:
    return smart.PLATFORM_LABELS.get(pid, pid)


def _describe(pl: dict[str, Any]) -> str:
    pieces: list[str] = []
    if pl["platforms"]:
        pieces.append("、".join(_label(p) for p in pl["platforms"]))
    if pl["kinds"]:
        pieces.append("、".join({"video": "视频", "images": "图文", "article": "文章",
                                "short": "动态", "list": "榜单"}.get(k, k) for k in pl["kinds"]))
    if pl["since"]:
        pieces.append("今天起")
    if pl["keyword"]:
        pieces.append("含「" + pl["keyword"] + "」")
    return " · ".join(pieces) if pieces else "全部"


def _reply_for(pl: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    if pl.get("reply"):
        return pl["reply"]
    where = _describe(pl)
    if not rows:
        return f"按「{where}」没找到内容，换个说法或者先刷新一轮。"
    if pl["mode"] == "browse":
        return f"随手挑了 {len(rows)} 条，{where}，换一批就再抽一组。"
    return f"按「{where}」挑了 {len(rows)} 条，按{'热度' if pl['sort'] == 'engagement' else '新鲜度'}排。"


def _suggestions(pl: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    if len(pl["platforms"]) > 1:
        out.append("只看 " + _label(pl["platforms"][0]))
    elif not pl["platforms"] and rows:
        first = rows[0].get("platform") or ""
        if first:
            out.append("只看 " + _label(first))
    if pl["sort"] == "freshness":
        out.append("换成最热的")
    else:
        out.append("换成最新的")
    if not pl["since"]:
        out.append("只要今天的")
    if not pl["keyword"]:
        out.append("找点 AI 的")
    return out[:3]


def _diversify(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """browse 模式按平台轮着取，避免一屏全是同一个平台。"""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get("platform") or ""), []).append(row)
    out: list[dict[str, Any]] = []
    while len(out) < limit and any(buckets.values()):
        for pid in list(buckets):
            bucket = buckets[pid]
            if bucket:
                out.append(bucket.pop(0))
                if len(out) >= limit:
                    break
    return out


def _decorate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        reasons = smart.reason_for(row, {})
        like = int(row.get("like_count") or 0)
        if like >= 1000 and len(reasons) < 2:
            reasons.append(f"{like // 1000}.{like % 1000 // 100} 千赞")
        row["reasons"] = reasons
    return rows


def chat(store, message: str, history: list[dict[str, str]] | None = None,
         limit: int = 12, exclude: list[str] | None = None) -> dict[str, Any]:
    """一句话找内容。优先走 agent（能自己搜、看结果、换词），失败静默退回旧路径。"""
    conf = settings_mod.load()
    chain = _provider_list(conf)
    if _agent_available(conf, chain):
        try:
            from . import agent as agent_mod  # 懒加载：import pydantic_ai 要 1.7s
            result = agent_mod.run(store, message, history=history, limit=limit,
                                   exclude=exclude, chain=chain,
                                   max_tools=int(conf.get("ai_agent_max_tools") or 10))
            _LAST.update({"at": int(time.time()), "provider": result.get("provider", ""),
                          "ok": True, "error": "", "tried": [p["name"] for p in chain]})
            return result
        except Exception as exc:  # noqa: BLE001 - 模型/工具/超时任何问题都退回旧路径
            _LAST.update({"at": int(time.time()), "provider": "",
                          "ok": False, "error": ("agent: " + str(exc or exc.__class__.__name__))[:200],
                          "tried": [p["name"] for p in chain]})
    return _chat_legacy(store, message, history=history, limit=limit, exclude=exclude)


def _chat_legacy(store, message: str, history: list[dict[str, str]] | None = None,
                 limit: int = 12, exclude: list[str] | None = None) -> dict[str, Any]:
    pl = plan(message, history)
    kind = pl["kinds"][0] if pl["kinds"] else None
    fetch = min(100, max(limit * 3, 24))
    rows, _next = store.page(platforms=pl["platforms"] or None, kind=kind, sort=pl["sort"],
                             limit=fetch, keyword=pl["keyword"] or None, since=pl["since"])
    if exclude:
        seen = set(exclude)
        rows = [r for r in rows if r.get("id") not in seen]
    # 同一平台同一个标题只留一条：热榜会把同一问题按不同 id 收进来两次
    seen_titles: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("platform") or ""), str(row.get("title") or "").strip())
        if key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(row)
    rows = unique
    if pl["mode"] == "browse":
        rows = _diversify(rows, limit)
    rows = _decorate(rows[:limit])
    return {
        "engine": pl["engine"],
        "provider": pl.get("provider", ""),
        "plan": {k: pl[k] for k in ("mode", "platforms", "kinds", "since", "keyword", "sort")},
        "reply": _reply_for(pl, rows),
        "items": rows,
        "count": len(rows),
        "suggestions": _suggestions(pl, rows),
        "understood": _describe(pl),
    }
