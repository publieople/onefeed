"""HTTP 路由（003 T30–T45）。

只读信息流 + 刷新编排 + 插件市场 + 登录状态。错误统一 {error:{code,message,hint}}。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import urllib.parse

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from plugin_runtime.host import PluginHost
from plugin_runtime.paths import state_root

from . import (__version__, ai as ai_mod, auth as auth_mod, market, media as media_mod,
               smart, settings as settings_mod, summary as summary_mod)
from .following import FOLLOWING_FEED, AccountsRunner, FollowingRunner
from .service import RefreshRunner, demo_mode, sync_installed
from .store import SORTS, Store

router = APIRouter(prefix="/api")

# 评论不像信息流那样每分钟在变，缓存十分钟，省掉反复起子进程的开销。
_COMMENT_CACHE: dict[tuple[str, int, str], tuple[float, dict[str, Any]]] = {}
COMMENT_TTL = 600

# 详情比评论变得还慢；6 小时足够，刷新按钮会显式 refresh=1 绕过。
DETAIL_TTL = 6 * 3600

# 直链过期的信号：小红书 CDN 的 t 签名过期回 403，抖音回 403/404。
# 401 也算——登录态掉了重取详情能顺手带上新 cookie。
_MEDIA_EXPIRED = frozenset({401, 403, 404, 410})
# 同一条内容 60 秒内只重取一次详情：前端一次播放会发好几个 Range 请求，
# 全放过等于同时起三个浏览器进程去抢同一个 profile。
MEDIA_REFRESH_COOLDOWN = 60
_MEDIA_REFRESH_AT: dict[str, float] = {}
_MEDIA_REFRESH_LOCK = threading.Lock()


def _claim_media_refresh(item_id: str) -> bool:
    """抢到「这条内容归我重取详情」的资格才返回 True，否则让别的请求等着看结果。"""
    now = time.time()
    with _MEDIA_REFRESH_LOCK:
        if now - _MEDIA_REFRESH_AT.get(item_id, 0.0) < MEDIA_REFRESH_COOLDOWN:
            return False
        _MEDIA_REFRESH_AT[item_id] = now
        for key in [k for k, at in _MEDIA_REFRESH_AT.items() if now - at > 3600]:
            _MEDIA_REFRESH_AT.pop(key, None)
        return True


def _store(request: Request) -> Store:
    return request.app.state.store


def _runner(request: Request) -> RefreshRunner:
    return request.app.state.refresher

def _following_runner(request: Request) -> FollowingRunner:
    return request.app.state.following

def _accounts_runner(request: Request) -> AccountsRunner:
    return request.app.state.accounts


def _plugin_host(request: Request) -> PluginHost:
    return request.app.state.refresher.host


# 关注页固定按这个顺序展示平台：B 站、抖音、小红书、知乎。
# 插件没装 / 没声明 following / 没登录 都要如实显示，而不是从列表里消失。
FOLLOWING_PLATFORMS = ("bilibili", "douyin", "xiaohongshu", "zhihu")
FOLLOWING_LABELS = {"bilibili": "B 站", "douyin": "抖音",
                    "xiaohongshu": "小红书", "zhihu": "知乎"}


def _login_probe(plugin_id: str) -> tuple[bool | None, str]:
    """只看本机凭证文件，不启动插件。返回 (是否已登录, 一句话说明)。

    None = 这个平台没有可读的 cookie 文件（B 站由 bili CLI 管），
    不能据此断言「没登录」；真正是否可用由同步结果说话。
    """
    spec = auth_mod.SPECS.get(plugin_id)
    if spec is None:
        if plugin_id == "bilibili":
            home = state_root() / "toolhome" / "bili-cli" / "credential.json"
            appdata = Path.home() / "AppData" / "Roaming" / "bili-cli" / "credential.json"
            if home.is_file() or appdata.is_file():
                return True, "B 站登录由 bili CLI 管理"
            return None, "B 站登录由本机 bili CLI 管理，同步失败时会说明"
        return None, ""
    path = state_root() / "cookies" / f"{plugin_id}.json"
    if path.is_file():
        names = auth_mod._cookie_names(plugin_id)
        if any(n.lower() in {c.lower() for c in spec["cookies"]} for n in names):
            return True, f"已登录（{len(names)} 个 cookie）"
    # 浏览器型插件可能只把登录态留在了持久档案里（cookie 文件是登录窗口顺手导出的副本）。
    # 档案在就说明「可能登录过」，这里不下「没登录」的结论，交给同步结果验证。
    profile = state_root() / "browser" / plugin_id / "Default" / "Preferences"
    if profile.is_file():
        return None, "浏览器档案已有，同步时会验证登录态"
    if path.is_file():
        return False, f"{spec['label']} cookie 里没有 {spec['cookies'][0]}，需要重新登录"
    return False, f"{spec['label']}还没登录"


def _looks_like_login_error(text: str) -> bool:
    """同步失败时，只有明确提到登录才敢把平台标成「需要登录」。"""
    low = str(text or "").lower()
    return any(word in low for word in ("登录", "login", "未登录", "认证", "cookie"))


def _following_platforms(request: Request) -> dict[str, Any]:
    runner = _following_runner(request)
    store = _store(request)
    manifests = {m.id: m for m in runner.manifests()}
    installed = {str(p["id"]) for p in store.list_plugins()}
    stats = runner.last_runs()
    counts = {str(r["platform"]): r for r in store.following_counts(FOLLOWING_FEED)}
    rows: list[dict[str, Any]] = []
    supported_ids = set(runner.platform_ids())
    for pid in FOLLOWING_PLATFORMS:
        manifest = manifests.get(pid)
        label = (manifest.name if manifest is not None and manifest.name
                 else FOLLOWING_LABELS.get(pid, pid))
        has_row = pid in installed or manifest is not None
        supported = pid in supported_ids
        logged_in, login_note = _login_probe(pid)
        stat = stats.get(pid) or {}
        count_row = counts.get(pid) or {}
        if not has_row:
            state, note = "not_installed", "还没安装这个平台的插件"
        elif not supported:
            state, note = "unsupported", "这个平台的插件还没有关注流能力"
        elif logged_in is False:
            state, note = "need_login", login_note
        elif stat.get("last_ok") is False and _looks_like_login_error(str(stat.get("error") or "")):
            state, note = "need_login", str(stat.get("error") or "上次同步要求登录")
        else:
            state, note = "ready", login_note
        rows.append({
            "platform": pid,
            "label": label,
            "installed": has_row,
            "supported": supported,
            "logged_in": logged_in,
            "state": state,
            "note": note,
            "count": int(count_row.get("count") or 0),
            "last_seen_at": int(count_row.get("last_seen_at") or 0),
            "last_sync_at": int(stat.get("last_run_at") or 0),
            "last_ok_at": int(stat.get("last_ok_at") or 0),
            "last_ok": stat.get("last_ok"),
            "saved_count": int(stat.get("count") or 0),
            "new_count": int(stat.get("new_count") or 0),
            "error": str(stat.get("error") or ""),
        })
    try:
        errors = list(request.app.state.refresher.host.errors)
    except Exception:
        errors = []
    return {"platforms": rows, "plugin_errors": errors,
            "counts": store.following_counts(FOLLOWING_FEED),
            "count": store.following_count(FOLLOWING_FEED),
            "syncing": runner.running(), "progress": runner.snapshot()}


def _account_platforms(request: Request) -> dict[str, Any]:
    """关注名单的平台状态。和关注流分开算：插件可能能抓内容、但拿不到名单。"""
    runner = _accounts_runner(request)
    store = _store(request)
    manifests = {m.id: m for m in runner.manifests()}
    installed = {str(p["id"]) for p in store.list_plugins()}
    stats = runner.last_runs()
    counts = {str(r["platform"]): r for r in store.following_account_counts()}
    rows: list[dict[str, Any]] = []
    for pid in FOLLOWING_PLATFORMS:
        manifest = manifests.get(pid)
        label = (manifest.name if manifest is not None and manifest.name
                 else FOLLOWING_LABELS.get(pid, pid))
        has_row = pid in installed or manifest is not None
        supported = pid in set(runner.platform_ids())
        logged_in, login_note = _login_probe(pid)
        stat = stats.get(pid) or {}
        count_row = counts.get(pid) or {}
        if not has_row:
            state, note = "not_installed", "还没安装这个平台的插件"
        elif not supported:
            state, note = "unsupported", "这个平台的插件还没有关注名单能力"
        elif logged_in is False:
            state, note = "need_login", login_note
        elif stat.get("last_ok") is False and _looks_like_login_error(str(stat.get("error") or "")):
            state, note = "need_login", str(stat.get("error") or "上次同步要求登录")
        else:
            state, note = "ready", login_note
        rows.append({
            "platform": pid, "label": label, "installed": has_row,
            "supported": supported, "logged_in": logged_in, "state": state, "note": note,
            "count": int(count_row.get("count") or 0),
            "total": int(count_row.get("total") or 0),
            "last_seen_at": int(count_row.get("last_seen_at") or 0),
            "last_sync_at": int(stat.get("last_run_at") or 0),
            "last_ok_at": int(stat.get("last_ok_at") or 0),
            "last_ok": stat.get("last_ok"),
            "error": str(stat.get("error") or ""),
        })
    try:
        errors = list(request.app.state.refresher.host.errors)
    except Exception:
        errors = []
    return {"platforms": rows, "plugin_errors": errors,
            "counts": store.following_account_counts(),
            "count": sum(int(r.get("count") or 0) for r in store.following_account_counts()),
            "syncing": runner.running(), "progress": runner.snapshot()}


@router.get("/following/accounts")
def following_accounts_list(
    request: Request,
    platform: str | None = Query(None, description="逗号分隔，例：bilibili,zhihu"),
    q: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """关注名单：只读「我关注了谁」，和关注流的内容是两件事。"""
    store = _store(request)
    wanted = [p.strip() for p in platform.split(",") if p.strip()] if platform else []
    single = wanted[0] if len(wanted) == 1 else None
    rows = store.following_accounts(platform=single, active=True, query=q, limit=1000)
    if len(wanted) > 1:
        rows = [r for r in rows if str(r.get("platform")) in wanted]
    elif not wanted:
        rows = [r for r in rows if str(r.get("platform")) in FOLLOWING_PLATFORMS]
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _account_platforms(request)
    return {"accounts": page, "next": (offset + limit) if offset + limit < total else None,
            "count": len(page), "total": total, "platforms": meta["platforms"],
            "plugin_errors": meta["plugin_errors"], "counts": meta["counts"],
            "syncing": meta["syncing"], "progress": meta["progress"]}


@router.post("/following/accounts/refresh")
def following_accounts_refresh(request: Request, body: dict[str, Any] | None = Body(None)) -> dict:
    body = body or {}
    platforms = body.get("platforms")
    if isinstance(platforms, str):
        platforms = [p.strip() for p in platforms.split(",") if p.strip()]
    if platforms is not None and not isinstance(platforms, list):
        raise HTTPException(status_code=422, detail={
            "code": "bad_platforms", "message": "platforms 必须是数组",
            "hint": '例：{"platforms": ["bilibili"]}'})
    runner = _accounts_runner(request)
    ok, state = runner.trigger(
        platforms=[str(p) for p in platforms] if platforms else None,
        force=bool(body.get("force")),
        source=str(body.get("source") or "user"),
        owner=str(body.get("owner") or ""),
    )
    if not ok and state.get("running"):
        raise HTTPException(status_code=409, detail={
            "code": "accounts_running", "message": "关注名单正在同步",
            "hint": "等这一轮跑完；关注页会自己刷新"})
    return {"ok": ok, "state": state}


@router.get("/following/accounts/progress")
def following_accounts_progress(request: Request) -> dict:
    return {"state": _accounts_runner(request).snapshot()}


@router.post("/following/accounts/cancel")
def following_accounts_cancel(request: Request, body: dict[str, Any] | None = Body(None)) -> dict:
    owner = str((body or {}).get("owner") or "") or None
    return {"ok": _accounts_runner(request).cancel(owner=owner)}


def _author_profile(request: Request, platform: str, account_id: str,
                    refresh: bool = False) -> dict[str, Any]:
    store = _store(request)
    account = store.get_following_account(platform, account_id)
    local = account or store.find_author(platform, account_id)
    profile = dict(local) if local else {"platform": platform, "account_id": account_id,
                                         "name": "", "avatar": "", "url": "", "bio": ""}
    error = ""
    if refresh or not profile.get("name"):
        try:
            remote = _plugin_host(request).author_profile(platform, account_id)
        except Exception as exc:
            remote = None
            error = f"{type(exc).__name__}: {exc}"[:300]
        if remote:
            for key in ("name", "avatar", "bio", "url", "following", "follower", "posts"):
                if remote.get(key):
                    profile[key] = remote[key]
            # 只刷新名单里已有的人；未关注作者的名片是临时展示，不能借读名片
            # 把他写进 following_accounts，否则「关注的人」会越看越多。
            if account:
                try:
                    store.upsert_following_accounts(platform, [{
                        "account_id": account_id,
                        "name": profile.get("name") or "",
                        "avatar": profile.get("avatar") or "",
                        "url": profile.get("url") or "",
                        "bio": profile.get("bio") or "",
                        "relation": profile.get("relation") or "following",
                    }], complete=False)
                except Exception:
                    pass
    profile["label"] = FOLLOWING_LABELS.get(platform, platform)
    profile["following"] = bool(account and account.get("active"))
    return {"profile": profile, "error": error}


@router.get("/authors/{platform}/{account_id}")
def author_page(request: Request, platform: str, account_id: str,
                refresh: bool = Query(False), cursor: str | None = Query(None),
                limit: int = Query(30, ge=1, le=100)) -> dict:
    """作者页：先给本地已有作品，再按需去平台补一页。"""
    store = _store(request)
    data = _author_profile(request, platform, account_id, refresh=refresh)
    items, next_cursor = store.author_items(platform, account_id, cursor=cursor, limit=limit)
    host = _plugin_host(request)
    try:
        remote_supported = any(m.id == platform and "author_posts" in m.features
                               for m in host.discover())
    except Exception:
        remote_supported = False
    return {"profile": data["profile"], "profile_error": data["error"],
            "items": items, "next": next_cursor, "count": len(items),
            "total": store.author_item_count(platform, account_id),
            "remote_supported": remote_supported,
            "platforms": _account_platforms(request)["platforms"],
            "plugin_errors": list(host.errors)}


@router.get("/authors/{platform}/{account_id}/posts")
def author_posts_local(request: Request, platform: str, account_id: str,
                       cursor: str | None = Query(None),
                       limit: int = Query(30, ge=1, le=100)) -> dict:
    store = _store(request)
    items, next_cursor = store.author_items(platform, account_id, cursor=cursor, limit=limit)
    return {"items": items, "next": next_cursor, "count": len(items),
            "total": store.author_item_count(platform, account_id)}


@router.post("/authors/{platform}/{account_id}/fetch")
def author_posts_fetch(request: Request, platform: str, account_id: str,
                       body: dict[str, Any] | None = Body(None)) -> dict:
    """从平台补一页作者作品。补回来的条目标 author_only，不进主信息流。"""
    body = body or {}
    cursor = str(body.get("cursor") or "") or None
    limit = max(1, min(int(body.get("limit") or 30), 50))
    store = _store(request)
    try:
        page = _plugin_host(request).author_posts(platform, account_id, cursor=cursor, limit=limit)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                "fetched": 0, "added": 0, "next": None,
                "total": store.author_item_count(platform, account_id)}
    items = list(page.get("items") or [])
    known = store.item_ids([it.id for it in items])
    added = sum(1 for it in items if it.id not in known)
    for it in items:
        # 只有第一次从作者页补进来的条目才标 author_only；同一条内容如果
        # 本来就在主信息流可见，不能因为作者页抓了一次就把它藏起来。
        it.author_only = it.id not in known
    if items:
        store.upsert_items(items, preserve_hidden=True)
    return {"ok": True, "fetched": len(items), "added": added,
            "next": page.get("next"), "error": "",
            "total": store.author_item_count(platform, account_id)}


@router.get("/following")
def following(
    request: Request,
    platform: str | None = Query(None, description="逗号分隔，例：bilibili,zhihu"),
    kind: str | None = Query(None),
    author: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    """关注流：只读平台原生关注的人发了什么，不混推荐流。"""
    platforms = [p.strip() for p in platform.split(",") if p.strip()] if platform else None
    store = _store(request)
    rows, next_cursor = store.following_page(platforms=platforms, kind=kind, author=author,
                                             cursor=cursor, limit=limit)
    meta = _following_platforms(request)
    return {"items": rows, "next": next_cursor, "count": len(rows),
            "platforms": meta["platforms"], "plugin_errors": meta["plugin_errors"],
            "counts": meta["counts"], "total": meta["count"],
            "syncing": meta["syncing"], "progress": meta["progress"]}


@router.post("/following/refresh")
def following_refresh(request: Request, body: dict[str, Any] | None = Body(None)) -> dict:
    body = body or {}
    platforms = body.get("platforms")
    if isinstance(platforms, str):
        platforms = [p.strip() for p in platforms.split(",") if p.strip()]
    if platforms is not None and not isinstance(platforms, list):
        raise HTTPException(status_code=422, detail={
            "code": "bad_platforms", "message": "platforms 必须是数组",
            "hint": '例：{"platforms": ["bilibili"]}'})
    runner = _following_runner(request)
    ok, state = runner.trigger(
        platforms=[str(p) for p in platforms] if platforms else None,
        force=bool(body.get("force")),
        source=str(body.get("source") or "user"),
        owner=str(body.get("owner") or ""),
    )
    if not ok and state.get("running"):
        raise HTTPException(status_code=409, detail={
            "code": "following_running", "message": "关注流正在同步",
            "hint": "等这一轮跑完；关注页会自己刷新"})
    return {"ok": ok, "state": state}


@router.get("/following/progress")
def following_progress(request: Request) -> dict:
    return {"state": _following_runner(request).snapshot()}


@router.post("/following/cancel")
def following_cancel(request: Request, body: dict[str, Any] | None = Body(None)) -> dict:
    owner = str((body or {}).get("owner") or "") or None
    return {"ok": _following_runner(request).cancel(owner=owner)}



def _sse(event: dict[str, Any]) -> str:
    """一条 SSE 事件。ensure_ascii=False 是必须的：中文别被转义成六字符，白白多占带宽。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _apply_settings(request: Request, conf: dict[str, Any],
                    touched: set[str] | None = None,
                    prev_registry: str | None = None) -> list[str]:
    """把设置落到活着的对象上，返回"这次真正生效了什么"给前端显示。"""
    runner = _runner(request)
    applied: list[str] = []

    limit = int(conf.get("per_plugin_limit") or 12)
    if runner.limit != limit:
        runner.limit = limit
        applied.append(f"每轮条数 → {limit}")
    following = getattr(request.app.state, "following", None)
    if following is not None and following.limit != limit:
        following.limit = limit

    days = int(conf.get("prune_days") or 14)
    if runner.prune_days != days:
        runner.prune_days = days
        applied.append(f"保留天数 → {days}")

    auto_update = bool(conf.get("auto_update"))
    if runner.auto_update != auto_update:
        runner.auto_update = auto_update
        applied.append("自动更新插件 → " + ("开" if auto_update else "关"))

    target = settings_mod.resolve_plugins_dir(str(conf.get("plugins_dir") or ""))
    current_dir = Path(str(getattr(runner.host, "plugins_dir", "") or ".")).resolve()
    if current_dir != target.resolve():
        _swap_plugin_host(request, target)
        applied.append(f"插件目录 → {target}")

    if touched and "registry_url" in touched and prev_registry is not None \
            and settings_mod.registry_url() != prev_registry:
        applied.append(f"registry → {settings_mod.registry_url()}（下一轮采集起用新源）")
    return applied


def _percentiles(store: Store, rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """每条内容在本平台内的热度分位（前 xx%）。跨平台不能直比热度，只能比名次。

    engage_score 是刷新时算好的平台内分位（0–1000），这里直接换算成百分比，
    不再按点赞数另算一遍 —— 否则「热榜第 1」和「播放 5 千」会被拿来同样对待。
    """
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        score = int(row.get("engage_score") or 0)
        if score <= 0:
            continue  # 没有互动数据就别编名次
        pct = max(1, round(101 - score / 10))
        if pct <= 50:  # 只有真的靠前才值得说
            out.setdefault(row["platform"], {})[row["id"]] = pct
    return out


STALE_SECONDS = 24 * 3600  # 超过一天没有新内容才算「长期没更新」，别把正常闲置当故障


def _platform_health(runner: RefreshRunner, store: Store) -> dict[str, Any]:
    """顶栏采集胶囊要能说清「哪个平台坏了 / 多久没动静」，这里算好一次给它。

    只看 items 表是不够的：一个平台连续失败时 items 还在，用户看到的只是「没新增」。
    所以把最近一次采集的成败、最后一次成功时间、插件是否还在都摊开。
    """
    now = int(time.time())
    try:
        manifests = runner.host.discover()
        errors = list(runner.host.errors)
    except Exception as exc:  # 插件目录整个读不动时，至少要能把原因带出去
        manifests = []
        errors = [f"{type(exc).__name__}: {exc}"[:300]]
    labels = {m.id: (m.name or m.id) for m in manifests}
    intervals = settings_mod.platform_intervals()
    rows = {str(p["platform"]): dict(p) for p in store.platforms()}
    recent = store.recent_runs(240)
    last_run: dict[str, dict[str, Any]] = {}
    last_ok: dict[str, int] = {}
    for run in recent:
        pid = str(run.get("plugin") or "")
        if not pid:
            continue
        if pid not in last_run:
            last_run[pid] = run
        if run.get("ok") == 1 and pid not in last_ok:
            last_ok[pid] = int(run.get("finished_at") or run.get("started_at") or 0)
    live = (runner.snapshot().get("plugins") or {})

    def row_of(pid: str, label: str, available: bool) -> dict[str, Any] | None:
        base = rows.get(pid) or {"platform": pid, "count": 0, "last_fetched_at": 0}
        run = last_run.get(pid) or {}
        current = live.get(pid) or {}
        # 装了但从来没抓过、库里也没内容的插件不进顶栏：顶栏说的是「我有什么」，
        # 不是「我装了什么」。设置页有完整的插件列表。
        if not (base.get("count") or run or current):
            return None
        last_ok_at = int(last_ok.get(pid) or 0)
        last_run_at = int(run.get("finished_at") or run.get("started_at") or 0)
        status = run.get("ok")
        last_attempt_ok = None if status is None else bool(status)
        failed = bool(last_run_at and status == 0 and last_run_at > last_ok_at)
        interrupted = bool(last_run_at and status is None and now - last_run_at > 600)
        interval = int(intervals.get(pid, 0) or 0)
        last_success = max(last_ok_at, int(base.get("last_fetched_at") or 0))
        stale_after = max(STALE_SECONDS, interval * 6) if interval else STALE_SECONDS
        stale = bool(last_success and now - last_success > stale_after)
        if not available:
            state = "unavailable"
        elif failed:
            state = "failed"
        elif stale:
            state = "stale"
        else:
            state = "ok"
        return {
            "platform": pid,
            "label": label,
            "count": int(base.get("count") or 0),
            "last_fetched_at": int(base.get("last_fetched_at") or 0),
            "last_run_at": last_run_at,
            "last_ok_at": last_ok_at,
            "last_ok": last_attempt_ok,
            "failed": failed,
            "interrupted": interrupted,
            "stale": stale,
            "available": available,
            "interval": interval,
            "state": state,
            "running": current.get("status") == "running",
            "error": str(run.get("error") or "")[:300],
            "note": str(current.get("note") or "")[:160],
        }

    out = [r for m in manifests if (r := row_of(m.id, labels.get(m.id, m.id), True))]
    seen = {m.id for m in manifests}
    # 库里有内容、插件却不在发现结果里：正是「B 站插件目录读不动」那种情况。
    # 不能因为插件缺失就让它从列表里消失，否则用户只会觉得「B 站没更新」。
    for pid in sorted(rows):
        if pid not in seen:
            row = row_of(pid, pid, False)
            if row:
                out.append(row)
    attention = sum(1 for p in out if p["state"] in ("failed", "stale", "unavailable"))
    return {"platforms": out, "plugin_errors": errors, "needs_attention": attention}


@router.get("/health")
def health(request: Request) -> dict:
    store = _store(request)
    runner = _runner(request)
    health_rows = _platform_health(runner, store)
    return {
        "ok": True, "version": __version__, "items": store.count(),
        "db": str(store.path), "plugins": len(store.list_plugins()),
        "platforms": health_rows["platforms"], "demo": demo_mode(),
        "refreshing": runner.running(),
        "plugin_errors": health_rows["plugin_errors"],
        "needs_attention": health_rows["needs_attention"],
    }


def _mask(conf: dict[str, Any]) -> dict[str, Any]:
    """key 只进不出：前端只需要知道"配没配"，写接口照收。"""
    out = dict(conf)
    for secret in settings_mod.SECRET_KEYS:
        if out.get(secret):
            out[secret] = ""
    providers = out.get("ai_providers")
    if isinstance(providers, list):
        masked: list[dict[str, Any]] = []
        for item in providers:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            masked.append({**item, "key": "", "key_set": bool(key),
                           "key_hint": ("…" + key[-4:]) if len(key) >= 8 else ""})
        out["ai_providers"] = masked
    return out


@router.get("/settings")
def get_settings(request: Request) -> dict:
    conf = settings_mod.load()
    plugins_dir = settings_mod.resolve_plugins_dir(str(conf.get("plugins_dir") or ""))
    return {
        "settings": _mask(conf),
        "ai": ai_mod.status(),
        "resolved": {"plugins_dir": str(plugins_dir),
                     "registry_url": settings_mod.registry_url(),
                     "state_dir": str(state_root())},
        "defaults": settings_mod.DEFAULTS,
        # 生效中的平台冷却（内置默认 + 用户覆盖），设置页拿它填初始值
        "intervals": settings_mod.platform_intervals(conf.get("platform_intervals")),
        "sorts": list(settings_mod.SORTS),
    }


@router.put("/settings")
def put_settings(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    # 保存前的生效值：只报告"真的变了"的项。前端整表提交，不能把每项都算成改过。
    before = settings_mod.load()
    prev_registry = settings_mod.registry_url()
    prev_intervals = settings_mod.platform_intervals(before.get("platform_intervals"))
    try:
        conf = settings_mod.save(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "bad_settings", "message": str(exc),
            "hint": "看 /api/settings 里的 defaults 与允许范围"})
    applied = _apply_settings(request, conf, set(payload or {}), prev_registry)
    after_intervals = settings_mod.platform_intervals(conf.get("platform_intervals"))
    changed_intervals = [pid for pid, sec in after_intervals.items()
                         if sec != prev_intervals.get(pid)]
    if changed_intervals:
        applied.append(f"平台间隔 → {len(changed_intervals)} 个平台改过（下一次抓取生效）")
    return {"ok": True, "settings": _mask(conf), "applied": applied, "ai": ai_mod.status(),
            "resolved": {"plugins_dir": str(settings_mod.resolve_plugins_dir(
                str(conf.get("plugins_dir") or ""))),
                "registry_url": settings_mod.registry_url()}}


@router.get("/ai/status")
def ai_status() -> dict:
    return ai_mod.status()


@router.post("/ai/test")
def ai_test(payload: dict[str, Any] = Body(default={})) -> dict:
    """测一个模型通不通。传 id 测已保存的，传 base_url + model + key 测还没保存的草稿。"""
    return ai_mod.test_provider(payload)


@router.post("/ai/chat")
def ai_chat(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail={
            "code": "empty_message", "message": "说一句话再问", "hint": "例如「今天 B 站有什么 AI 的」"})
    history = payload.get("history")
    exclude = payload.get("exclude")
    try:
        limit = int(payload.get("limit") or 12)
    except (TypeError, ValueError):
        limit = 12
    limit = max(1, min(limit, 24))
    return ai_mod.chat(
        _store(request), message,
        history=history if isinstance(history, list) else None,
        limit=limit,
        exclude=[str(x) for x in exclude] if isinstance(exclude, list) else None,
    )


# ---------------------------------------------------------------- agent（011）
def _agent_runtime():
    """懒加载：关掉 agent 时连 pydantic_ai 都不 import（010 的开关语义）。"""
    from . import agent_runtime
    return agent_runtime


def _agent_ready() -> tuple[bool, str]:
    conf = settings_mod.load()
    if not ai_mod._agent_enabled(conf):
        return False, "Agent 开关关着"
    if not ai_mod._provider_list():
        return False, "还没配模型"
    return True, ""


@router.post("/agent/runs", status_code=202)
def agent_run_create(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail={
            "code": "empty_message", "message": "说一句话再问",
            "hint": "例如「把今天 B 站讲 AI 的挑三条存起来」"})
    ok, why = _agent_ready()
    if not ok:
        raise HTTPException(status_code=409, detail={
            "code": "agent_unavailable", "message": why,
            "hint": "去设置页打开 Agent 或填一个模型 key"})
    try:
        limit = int(payload.get("limit") or 12)
    except (TypeError, ValueError):
        limit = 12
    limit = max(1, min(limit, 24))
    exclude = payload.get("exclude")
    history = payload.get("history")
    runtime = _agent_runtime()
    return runtime.start(
        _store(request), message,
        history=history if isinstance(history, list) else None,
        limit=limit,
        exclude=[str(x) for x in exclude] if isinstance(exclude, list) else None,
        chain=ai_mod._provider_list(),
        max_tools=int(settings_mod.load().get("ai_agent_max_tools") or 10),
        runner=_runner(request),
        thread_id=str(payload.get("thread_id") or ""),
        context=payload.get("context") if isinstance(payload.get("context"), dict) else None,
    )


@router.get("/agent/runs/{run_id}/events")
def agent_run_events(request: Request, run_id: str) -> StreamingResponse:
    """SSE：实时事件流。断线重连带 Last-Event-ID 就能续上（事件本来就在库里）。"""
    runtime = _agent_runtime()
    store = _store(request)
    if store.get_agent_run(run_id, steps=False) is None:
        raise HTTPException(status_code=404, detail={"code": "no_run",
                                                     "message": "没有这条运行"})
    try:
        after = int(request.headers.get("last-event-id") or 0)
    except ValueError:
        after = 0
    return StreamingResponse(
        runtime.sse_stream(store, run_id, after=after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"})


@router.get("/agent/runs/{run_id}")
def agent_run_get(request: Request, run_id: str) -> dict:
    """回放：事件流从库里读，刷新页面 / 换设备都能看。"""
    run = _store(request).get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "no_run",
                                                     "message": "没有这条运行"})
    return {"run": run, "events": run.get("events", [])}


@router.post("/agent/runs/{run_id}/confirm")
def agent_run_confirm(request: Request, run_id: str,
                      payload: dict[str, Any] = Body(default={})) -> dict:
    confirm_id = str(payload.get("confirm_id") or "")
    if not confirm_id:
        raise HTTPException(status_code=400, detail={"code": "no_confirm",
                                                     "message": "缺 confirm_id"})
    ok = _agent_runtime().resolve_confirm(run_id, confirm_id, bool(payload.get("allow")))
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "confirm_expired",
                                                     "message": "这条确认已过期"})
    return {"ok": True, "allow": bool(payload.get("allow"))}


@router.post("/agent/runs/{run_id}/answer")
def agent_run_answer(request: Request, run_id: str,
                     payload: dict[str, Any] = Body(default={})) -> dict:
    """用户回答 Agent 的提问：选项 + 可选自由文本，一起塞回等待中的那一轮。"""
    ask_id = str(payload.get("ask_id") or "")
    if not ask_id:
        raise HTTPException(status_code=400, detail={"code": "no_ask",
                                                     "message": "缺 ask_id"})
    selected = payload.get("selected")
    ok = _agent_runtime().resolve_answer(
        run_id, ask_id,
        [str(x) for x in selected] if isinstance(selected, list) else [],
        str(payload.get("text") or ""))
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "ask_expired",
                                                     "message": "这条提问已经收尾了"})
    return {"ok": True}


@router.get("/agent/threads")
def agent_threads(request: Request, limit: int = Query(20, ge=1, le=100)) -> dict:
    """会话列表：侧栏「最近」用。"""
    threads = _store(request).recent_threads(limit=limit)
    return {"threads": threads, "count": len(threads)}


@router.get("/agent/threads/{thread_id}")
def agent_thread(request: Request, thread_id: str, limit: int = Query(40, ge=1, le=100),
                 events: bool = Query(True)) -> dict:
    """一段对话的完整问答对，默认连事件流一起给。

    回放要复原「上次给我看的那几条」：结果卡片、计划、轨迹都只存在 done 事件的
    payload 里，不带事件就只能铺文字。只想要文本列表时传 ?events=0。
    """
    store = _store(request)
    runs = store.thread_runs(thread_id, limit=limit, steps=events)
    return {"thread_id": thread_id, "runs": runs, "count": len(runs)}


@router.post("/agent/save")
def agent_save(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    """卡片 / 结果列表上的收藏按钮（不经过模型）。"""
    item_id = str(payload.get("id") or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail={"code": "no_id", "message": "缺 id"})
    on = bool(payload.get("on", True))
    mark = _store(request).mark_item(item_id, saved=on)
    return {"ok": True, "id": item_id, "saved": bool(mark.get("saved"))}


@router.post("/agent/runs/{run_id}/cancel")
def agent_run_cancel(request: Request, run_id: str) -> dict:
    """置停止位，交给跑着的那条线程自己收尾（它会写 cancelled 事件并落库）。

    以前这里直接把 run 标成 cancelled：库先变了、线程还在跑工具，SSE 立刻收流，
    前端只能看到「事件流断了」，模型却可能继续发动作。
    """
    ok = _agent_runtime().cancel(run_id)
    return {"ok": ok, "cancelling": ok}


@router.get("/agent/runs")
def agent_run_list(request: Request, thread_id: str | None = Query(None),
                   limit: int = Query(20, ge=1, le=100),
                   events: bool = Query(False)) -> dict:
    """事件流水默认不带上（一轮几十条）；设置页活动列表要撤销按钮时才加 ?events=1。"""
    runs = _store(request).recent_agent_runs(thread_id=thread_id, limit=limit, steps=events)
    return {"runs": runs, "count": len(runs)}


@router.get("/agent/actions")
def agent_actions() -> dict:
    """动作白名单：设置页「Agent 能做什么」直接渲染这个。"""
    from . import actions as actions_mod
    return {"actions": actions_mod.catalog()}


@router.post("/agent/undo")
def agent_undo(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    from . import actions as actions_mod
    token = str(payload.get("token") or "")
    if not token:
        raise HTTPException(status_code=400, detail={"code": "no_token",
                                                     "message": "缺 undo token"})
    return actions_mod.apply_undo(_store(request), token)


@router.get("/agent/saved")
def agent_saved(request: Request, limit: int = Query(50, ge=1, le=200)) -> dict:
    items = _store(request).saved_items(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/agent/summaries")
def agent_summaries(request: Request, limit: int = Query(30, ge=1, le=100),
                    offset: int = Query(0, ge=0)) -> dict:
    """最近生成过 AI 总结的条目，右栏「AI 总结」页用。"""
    rows = _store(request).summarized_items(limit=limit + 1, offset=offset)
    items = rows[:limit]
    return {"items": items, "count": len(items), "has_more": len(rows) > limit}


@router.post("/agent/mark")
def agent_mark(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    """卡片上的收藏/已读/隐藏按钮（不经过模型）。"""
    item_id = str(payload.get("id") or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail={"code": "no_id", "message": "缺 id"})
    store = _store(request)
    if store.get_item(item_id) is None:
        raise HTTPException(status_code=404, detail={"code": "no_item",
                                                     "message": "库里没有这条"})
    def _flag(key: str) -> bool | None:
        value = payload.get(key)
        return None if value is None else bool(value)
    mark = store.mark_item(item_id, saved=_flag("saved"), read=_flag("read"),
                           hidden=_flag("hidden"))
    return {"ok": True, "mark": mark}


@router.get("/favorites")
def favorite_list(request: Request, limit: int = Query(50, ge=1, le=200),
                  offset: int = Query(0, ge=0)) -> dict:
    """收藏夹列表：与「稍后再看」分开，按加入收藏夹的时间倒序。"""
    rows = _store(request).favorite_items(limit=limit + 1, offset=offset)
    items = rows[:limit]
    return {"items": items, "count": len(items), "has_more": len(rows) > limit}


@router.get("/favorites/{item_id}")
def favorite_status(request: Request, item_id: str) -> dict:
    return _store(request).get_favorite(item_id)


@router.put("/favorites/{item_id}")
def favorite_put(request: Request, item_id: str,
                 payload: dict[str, Any] = Body(default={})) -> dict:
    """收藏一条：备注必填（收藏夹的意义就是记下为什么留）。"""
    note = str(payload.get("note") or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail={
            "code": "need_note", "message": "写一句为什么收藏这一条",
            "hint": "收藏夹不是收藏按钮，备注是它和稍后再看的区别"})
    store = _store(request)
    if store.get_item(item_id) is None:
        raise HTTPException(status_code=404, detail={"code": "no_item",
                                                     "message": "库里没有这条"})
    return {"ok": True, "favorite": store.favorite_item(item_id, note)}


@router.delete("/favorites/{item_id}")
def favorite_delete(request: Request, item_id: str) -> dict:
    removed = _store(request).unfavorite_item(item_id)
    return {"ok": True, "removed": removed}


@router.get("/feed")
def feed(
    request: Request,
    platform: str | None = Query(None, description="逗号分隔，例：bilibili,xiaohongshu"),
    kind: str | None = Query(None, description="video / images / article / short / list"),
    sort: str = Query("freshness"),
    cursor: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    q: str | None = Query(None, description="一句话过滤，例：只看今天 B 站的 AI"),
    keyword: str | None = Query(None),
    since: int | None = Query(None, description="unix 秒，只要这之后发布的"),
    saved: bool = Query(False, description="只看收藏过的条目"),
) -> dict:
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail={
            "code": "bad_sort", "message": f"不支持的排序：{sort}",
            "hint": f"可选：{', '.join(SORTS)}"})
    parsed = smart.parse_query(q) if q else None
    platforms = [p.strip() for p in platform.split(",") if p.strip()] if platform else None
    if parsed:
        platforms = parsed["platforms"] or platforms
        kind = parsed["kinds"][0] if parsed["kinds"] else kind
        since = parsed["since"] or since
        keyword = parsed["keyword"] or keyword
    store = _store(request)
    rows, next_cursor = store.page(platforms=platforms, kind=kind, sort=sort,
                                   cursor=cursor, limit=limit, keyword=keyword, since=since,
                                   saved=saved)
    clusters = store.cluster_sizes([r.get("cluster_id") or "" for r in rows])
    pct = _percentiles(store, rows)
    for row in rows:
        info = clusters.get(row.get("cluster_id") or "", {})
        row["cluster_size"] = int(info.get("size", 0)) if info.get("size", 0) > 1 else 0
        row["cluster_platforms"] = info.get("platforms", []) if row["cluster_size"] else []
        stats = {"platforms": row["cluster_platforms"],
                 "percentile": pct.get(row["platform"], {}).get(row["id"])}
        row["reasons"] = smart.reason_for(row, stats)
    return {"items": rows, "next": next_cursor, "count": len(rows), "parsed": parsed}


@router.get("/item/{item_id}")
def item(request: Request, item_id: str) -> dict:
    store = _store(request)
    row = store.get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found", "message": f"没有这条内容：{item_id}",
            "hint": "id 形如 <插件 id>:<平台原生 id>，可从 /api/feed 的返回里取"})
    siblings = []
    cluster_size = 0
    cluster_platforms: list[str] = []
    if row.get("cluster_id"):
        sib_rows = store.conn.execute(
            "SELECT id, platform, title, author, url, published_at FROM items "
            "WHERE cluster_id = ? AND id != ? ORDER BY platform", (row["cluster_id"], item_id)
        ).fetchall()
        siblings = [dict(r) for r in sib_rows]
        if siblings:
            cluster_size = len(siblings) + 1
            cluster_platforms = sorted({row["platform"], *[s["platform"] for s in siblings]})
    # 详情页也要给出「为什么推给你」，否则卡片上有、点开反而没有了
    pct = _percentiles(store, [row])
    row["cluster_size"] = cluster_size
    row["cluster_platforms"] = cluster_platforms
    row["reasons"] = smart.reason_for(row, {
        "platforms": cluster_platforms,
        "percentile": pct.get(row["platform"], {}).get(row["id"]),
    })
    return {"item": row, "siblings": siblings}


@router.get("/item/{item_id}/comments")
def item_comments(request: Request, item_id: str, limit: int = Query(20, ge=1, le=50),
                  cursor: str | None = Query(None), refresh: bool = Query(False)) -> dict:
    """评论是插件的可选能力：实现了 comments() 的平台才有，没实现的照常出卡片。"""
    store = _store(request)
    row = store.get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found", "message": f"没有这条内容：{item_id}",
            "hint": "从 /api/feed 的返回里取 id"})
    plugin_id = row["platform"]
    host = _runner(request).host
    if not host.supports(plugin_id, "comments"):
        return {"supported": False, "items": [], "count": 0,
                "reason": "这个平台暂时读不到评论。"}

    key = (item_id, limit, cursor or "")
    now = time.time()
    cached = _COMMENT_CACHE.get(key)
    if cached and not refresh and now - cached[0] < COMMENT_TTL:
        return {**cached[1], "from_cache": True}

    try:
        page = host.comments(plugin_id, row, limit=limit, cursor=cursor)
    except RuntimeError as exc:
        message = str(exc)
        if "插件未实现" in message:
            return {"supported": False, "items": [], "count": 0,
                    "reason": "这个平台暂时读不到评论。"}
        return {"supported": True, "items": [], "count": 0, "next": None,
                "error": message[:300]}

    items = page["items"]
    payload = {"supported": True, "items": items, "count": len(items),
               "limit": limit, "next": page["next"]}
    _COMMENT_CACHE[key] = (now, payload)
    return payload


def _cache_chunks(payload: dict, size: int = 18) -> list[str]:
    """把已缓存的结构化小结拼回行协议文本，切块后逐块发。

    行协议与 summary_mod.stream_build 的正文格式保持一致：tldr 一行、要点一行一条、
    备注一行。前端 parseStreamText 就是按这个解，缓存命中和新生成才会长得一样。
    """
    lines: list[str] = []
    tldr = str(payload.get("tldr") or "").strip()
    if tldr:
        lines.append("TLDR: " + tldr)
    for point in payload.get("points") or []:
        if not isinstance(point, dict):
            continue
        text = str(point.get("text") or "").strip()
        if not text:
            continue
        at = point.get("t")
        prefix = ""
        if isinstance(at, (int, float)) and at >= 0:
            prefix = f"[{int(at) // 60}:{int(at) % 60:02d}] "
        lines.append("- " + prefix + text)
    caveat = str(payload.get("caveat") or "").strip()
    if caveat:
        lines.append("注意：" + caveat)
    raw = "\n".join(lines)
    return [raw[i:i + size] for i in range(0, len(raw), size)] or [""]


def _depth(raw: Any) -> str:
    """档位归一：不认识的值回落设置里的默认档。旧链接、手改的 URL 都不该报错。"""
    value = str(raw or "").strip()
    if value in summary_mod.DEPTHS:
        return value
    return summary_mod.configured_depth()


@router.get("/item/{item_id}/summary")
def item_summary(request: Request, item_id: str, refresh: bool = Query(False),
                 depth: str = Query("")) -> dict:
    """AI 总结：插件交素材、宿主出摘要，模型不可用时按素材顺序摘原句。

    每一档单独缓存：切档位看到的是那一档自己的正文，不是上一档的。
    """
    store = _store(request)
    row = store.get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found", "message": f"没有这条内容：{item_id}",
            "hint": "从 /api/feed 的返回里取 id"})
    level = _depth(depth)

    if not refresh:
        cached = store.get_summary(item_id, level)
        if cached and isinstance(cached.get("payload"), dict) and cached["payload"].get("tldr") is not None:
            return {"ok": True, "summary": cached["payload"], "from_cache": True,
                    "fetched_at": cached["fetched_at"]}

    try:
        payload = summary_mod.build(store, _runner(request).host, row, level)
    except Exception as exc:  # noqa: BLE001 - 前端只要一句原因
        return {"ok": False, "error": str(exc)[:300]}

    store.save_summary(item_id, payload, level)
    return {"ok": True, "summary": payload, "from_cache": False,
            "fetched_at": int(time.time())}


@router.get("/item/{item_id}/summary/stream")
def item_summary_stream(request: Request, item_id: str,
                        refresh: bool = Query(False),
                        depth: str = Query("")) -> StreamingResponse:
    """AI 总结（流式）：一行行吐，用户不用干等十几秒盯一块骨架屏。

    事件协议：meta → delta* → done（或 error），每条都是 data: {json}\n\n。
    """
    store = _store(request)
    row = store.get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found", "message": f"没有这条内容：{item_id}",
            "hint": "从 /api/feed 的返回里取 id"})
    host = _runner(request).host
    level = _depth(depth)

    def events() -> Any:
        # 先发一个注释行：浏览器收到首块才会把状态从「连接中」切过来
        yield ": open\n\n"
        if not refresh:
            cached = store.get_summary(item_id, level)
            if cached and isinstance(cached.get("payload"), dict) \
                    and cached["payload"].get("tldr") is not None:
                payload = cached["payload"]
                # 缓存命中也要发 delta：只发 done 的话前端那边是「一亮就是整篇」，
                # 和未缓存条目（逐字出来）观感不一致，用户会以为卡了一下才蹦出来。
                yield _sse({"type": "status", "phase": "writing"})
                for chunk in _cache_chunks(payload):
                    yield _sse({"type": "delta", "text": chunk})
                yield _sse({"type": "done", "from_cache": True, "summary": payload})
                return
        try:
            for event in summary_mod.stream_build(store, host, row, level):
                if event.get("type") == "done" and isinstance(event.get("summary"), dict):
                    try:
                        store.save_summary(item_id, event["summary"], level)
                    except Exception:  # noqa: BLE001 - 存不进缓存也别让流断在半路
                        pass
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - 前端只要一句原因
            yield _sse({"type": "error", "message": str(exc)[:300]})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"})


@router.post("/item/{item_id}/chat/stream")
def item_chat_stream(request: Request, item_id: str,
                     payload: dict[str, Any] = Body(default={})) -> StreamingResponse:
    """就着这一条内容对话：和总结用同一套 SSE 形状，前端一套读法就够。

    上下文 = 素材 + 当前这篇总结 + 最近几轮，所以追问细节不用把素材再喂一遍。
    """
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail={
            "code": "empty_message", "message": "说一句再问",
            "hint": "比如「这段到底在讲什么」"})
    store = _store(request)
    row = store.get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found", "message": f"没有这条内容：{item_id}",
            "hint": "从 /api/feed 的返回里取 id"})

    level = _depth(payload.get("depth"))
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else None
    history = payload.get("history") if isinstance(payload.get("history"), list) else None
    host = _runner(request).host

    def events() -> Any:
        yield ": open\n\n"
        try:
            messages = summary_mod.chat_messages(store, host, row, summary, history,
                                                 message, level)
        except Exception as exc:  # noqa: BLE001 - 素材取不到就别起请求
            yield _sse({"type": "error", "message": str(exc)[:300]})
            return
        thinking = False
        provider_name = ""
        try:
            for kind, piece, provider in ai_mod.stream_complete(
                    messages, max_tokens=900, temperature=0.4):
                provider_name = str(provider.get("name") or provider_name)
                if kind == "thinking":
                    if not thinking:
                        thinking = True
                        yield _sse({"type": "status", "phase": "thinking"})
                    continue
                yield _sse({"type": "delta", "text": piece})
            yield _sse({"type": "done", "provider": provider_name})
        except Exception as exc:  # noqa: BLE001 - 中途断了也要说清断在哪
            note = (str(exc) or exc.__class__.__name__)[:300]
            if note == "没有配置模型 key":
                note = "还没配模型 key，去设置页填一个再问。"
            yield _sse({"type": "error", "message": note})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"})


@router.get("/item/{item_id}/detail")
def item_detail(request: Request, item_id: str, refresh: bool = Query(False)) -> dict:
    """详情是插件的可选能力：没实现的插件照常出卡片，只是点开没有正文。"""
    store = _store(request)
    row = store.get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found", "message": f"没有这条内容：{item_id}",
            "hint": "从 /api/feed 的返回里取 id"})
    plugin_id = row["platform"]
    host = _runner(request).host
    if not host.supports(plugin_id, "detail"):
        return {"supported": False, "detail": None,
                "reason": "这个平台暂时只能在原站看。"}

    if not refresh:
        cached = store.get_detail(item_id, max_age=DETAIL_TTL)
        if cached:
            return {"supported": True, "detail": cached["payload"], "from_cache": True,
                    "fetched_at": cached["fetched_at"]}

    try:
        detail = host.detail(plugin_id, row)
    except RuntimeError as exc:
        message = str(exc)
        if "插件未实现" in message:
            return {"supported": False, "detail": None,
                    "reason": "这个平台暂时只能在原站看。"}
        return {"supported": True, "detail": None, "error": message[:300]}

    store.save_detail(item_id, detail)
    return {"supported": True, "detail": detail, "from_cache": False,
            "fetched_at": int(time.time())}


@router.get("/media/{item_id}/{slot}")
def media(request: Request, item_id: str, slot: str,
          range_header: str | None = Header(None, alias="Range")):
    """媒体边车：只回 details 表里存过的地址，前端给不了 URL。

    存在的理由只有一个——抖音直链要 Referer。别的平台能直连就别走这里。
    """
    if not media_mod.SLOT_RE.match(slot):
        raise HTTPException(status_code=404, detail={
            "code": "bad_slot", "message": f"不认识的媒体位：{slot}",
            "hint": "只有 video / poster / img-0 … img-11"})

    store = _store(request)
    row = store.get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found", "message": f"没有这条内容：{item_id}", "hint": ""})
    cached = store.get_detail(item_id, max_age=0)
    if not cached:
        raise HTTPException(status_code=404, detail={
            "code": "detail_not_ready", "message": "还没有这条内容的详情缓存，媒体地址没地方取",
            "hint": "先打开一次详情，再播放"})
    payload = cached["payload"]
    plugin_id = row["platform"]
    try:
        manifest = _runner(request).host.get(plugin_id)
        hosts = list(manifest.media_hosts)
    except Exception:
        hosts = []

    detail_refreshed = False
    while True:
        target = media_mod.resolve_slot(payload, slot)
        if target is None:
            raise HTTPException(status_code=404, detail={
                "code": "media_missing", "message": f"这条内容没有 {slot} 这个媒体位", "hint": ""})

        url_host = (urllib.parse.urlparse(target["url"]).hostname or "").lower()
        cookie = (media_mod.cookie_header(plugin_id)
                  if media_mod._host_allowed(url_host, hosts) else "")

        sem = media_mod.semaphore_for(slot)
        if not sem.acquire(timeout=20):
            raise HTTPException(status_code=503, detail={
                "code": "busy", "message": "同时在拉的媒体太多了", "hint": "等一会儿再试"})
        try:
            status, headers, resp = media_mod.open_stream(
                target["url"], referer=target["referer"], cookie=cookie, range_header=range_header)
        except media_mod.MediaBlocked:
            sem.release()
            raise HTTPException(status_code=400, detail={
                "code": "media_blocked",
                "message": "这条媒体地址指向本机或内网，服务端不会去取。",
                "hint": "去原帖看，或者换一条内容"})
        except Exception as exc:  # 网络层失败：别把半截流当成功
            sem.release()
            raise HTTPException(status_code=502, detail={
                "code": "media_failed", "message": f"取媒体失败：{exc}"[:300],
                "hint": "点原帖试试"})

        if status < 400:
            break

        try:
            resp.close()
        finally:
            sem.release()

        # T46：签名直链过期是常态（小红书 t / 抖音 play_addr），重取一次详情换地址再试一次。
        # 只重试一次，且同一个 item 60 秒内只让一个请求去重取，避免播放器的多段 Range 同时开浏览器。
        if status in _MEDIA_EXPIRED and not detail_refreshed and _claim_media_refresh(item_id):
            detail_refreshed = True
            try:
                fresh = _runner(request).host.detail(plugin_id, row)
            except Exception as exc:
                raise HTTPException(status_code=502, detail={
                    "code": "media_expired",
                    "message": f"直链过期了，重取详情也没成功：{str(exc)[:200]}",
                    "hint": "先去详情页点一次刷新，或者直接去原帖看"})
            if isinstance(fresh, dict) and fresh:
                store.save_detail(item_id, fresh)
                payload = fresh
                continue

        raise HTTPException(status_code=502, detail={
            "code": "media_expired" if status in _MEDIA_EXPIRED else "media_failed",
            "message": f"平台拒绝了这次取流（HTTP {status}）",
            "hint": ("直链过期，重取详情也没拿到新地址，去原帖看吧"
                     if status in _MEDIA_EXPIRED else "过一会儿再试，或者去原帖看")})

    out = {k: headers[k] for k in
           ("content-type", "content-length", "content-range", "accept-ranges", "etag", "last-modified")
           if k in headers}
    # 边车地址对同一条内容是不变的（过期了服务端自己会重取），所以让浏览器存十分钟：
    # 否则每滚回一屏、每换一次筛选都要把封面重新拉一遍（实测单张 312 kB）。
    out["cache-control"] = "public, max-age=600, stale-while-revalidate=60"

    # 过了 max-age 的那部分请求：ETag 对得上就直接 304，别再流一遍字节
    etag = headers.get("etag")
    if etag and request.headers.get("if-none-match") == etag:
        try:
            resp.close()
        finally:
            sem.release()
        return Response(status_code=304, headers={"etag": etag,
                                                  "cache-control": out["cache-control"]})

    def _body():
        try:
            yield from media_mod.iter_body(resp)
        finally:
            sem.release()

    return StreamingResponse(_body(), status_code=status, headers=out,
                             media_type=headers.get("content-type", "application/octet-stream"))


@router.post("/refresh", status_code=202)
def refresh(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    platforms = payload.get("platforms") if isinstance(payload, dict) else None
    # force=true：用户明确要求「现在就抓」，越过平台冷却（默认不越：防的是风控）
    force = bool(payload.get("force")) if isinstance(payload, dict) else False
    # 滚到底的自动检查带 source=auto：前端据此只把新条目并进列表，不触发展开/收起演出。
    source = str(payload.get("source") or "user") if isinstance(payload, dict) else "user"
    _COMMENT_CACHE.clear()  # 新一轮采集后评论可能变了，别拿旧缓存糊弄
    started, state = _runner(request).trigger(platforms=platforms, force=force, source=source)
    if not started:
        raise HTTPException(status_code=409, detail={
            "code": "refresh_running", "message": "已经在刷新了",
            "hint": "等这一轮结束，或者看 /api/progress 的进度"})
    return {"ok": True, "state": state}


@router.get("/progress")
def progress(request: Request) -> dict:
    return {"state": _runner(request).snapshot()}


@router.get("/summary")
def summary(request: Request) -> dict:
    return smart.summary(_store(request))


@router.get("/plugins")
def plugins(request: Request, refresh_market: bool = Query(False)) -> dict:
    store = _store(request)
    host = _runner(request).host
    if refresh_market:
        # 「刷新目录」不只是刷新 registry：目录是事实，库只是索引。
        # prune=True 会把「目录已经被手工删掉」的幽灵记录清掉，市场页才会重新出现「安装」。
        try:
            sync_installed(store, Path(str(host.plugins_dir)), prune=True)
        except OSError:
            pass
    try:
        manifests = {m.id: m for m in host.discover()}
    except Exception:
        manifests = {}
    installed = []
    for row in store.list_plugins():
        manifest = manifests.get(row["id"])
        installed.append({
            **row,
            "version": manifest.version if manifest else row["version"],
            "name": manifest.name if manifest else row["id"],
            "description": manifest.description if manifest else "",
            "capabilities": sorted(manifest.capabilities) if manifest else [],
            "features": sorted(manifest.features) if manifest else [],
        })
    return {"installed": installed, "market": market.merged(store, force=refresh_market),
            "plugins_dir": str(host.plugins_dir),
            "errors": list(getattr(host, "errors", []) or [])}


@router.post("/plugins/{plugin_id}/install")
def install_plugin(request: Request, plugin_id: str) -> dict:
    store = _store(request)
    try:
        result = market.install(store, plugin_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={
            "code": "install_failed", "message": f"{type(exc).__name__}: {exc}"[:300],
            "hint": "检查网络、registry 缓存，或改用本地文件安装"})
    _reload_plugins(request)
    return {"ok": True, "result": result}


def _swap_plugin_host(request: Request, target: Path) -> PluginHost:
    """换插件目录时，主信息流与关注流必须拿到同一个新宿主。

    只换 refresher.host 会让 following / accounts 继续拿着旧宿主：新装的插件
    在关注页不出现，卸载后还在。目录是事实，库只是索引，换完顺手同步。
    """
    target = Path(target)
    host = PluginHost(plugins_dir=target)
    _runner(request).host = host
    for runner_name in ("following", "accounts"):
        runner = getattr(request.app.state, runner_name, None)
        if runner is not None:
            runner.host = host
    sync_installed(_store(request), target)
    return host


def _reload_plugins(request: Request) -> None:
    """装/更新/卸载之后重新发现插件：沿用当前生效目录，不重新读设置。

    create_app() 可以显式传 plugins_dir（测试与嵌入式使用），这时设置里的目录
    不是事实来源；装完插件再按设置解析会把宿主切到另一个目录，新插件就“消失”。
    """
    current = getattr(_runner(request).host, "plugins_dir", None)
    if current:
        _swap_plugin_host(request, Path(current))
        return
    conf = settings_mod.load()
    target = settings_mod.resolve_plugins_dir(str(conf.get("plugins_dir") or ""))
    _swap_plugin_host(request, target)


@router.post("/plugins/{plugin_id}/update")
def update_plugin(request: Request, plugin_id: str) -> dict:
    store = _store(request)
    try:
        result = market.update(store, plugin_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={
            "code": "update_failed", "message": f"{type(exc).__name__}: {exc}"[:300],
            "hint": "先看市场页的版本与 sha256；更新走的是和安装同一条下载校验链路"})
    _reload_plugins(request)
    return {"ok": True, "result": result}


@router.post("/market/update-all")
def update_all_plugins(request: Request) -> dict:
    store = _store(request)
    result = market.update_all(store)
    if result.get("updated"):
        _reload_plugins(request)
    return {"ok": True, "result": result}


@router.get("/market/updates")
def market_updates(request: Request) -> dict:
    """只报「可更新」，不下载。市场页与设置页共用一个口径。"""
    store = _store(request)
    items = market.pending_updates(store)
    return {"count": len(items), "items": items}


@router.delete("/plugins/{plugin_id}")
def uninstall_plugin(request: Request, plugin_id: str) -> dict:
    store = _store(request)
    try:
        result = market.uninstall(store, plugin_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={
            "code": "uninstall_failed", "message": f"{type(exc).__name__}: {exc}"[:300],
            "hint": "目录可能被占用或没有删除权限；目录已不存在时现在也会清理库记录"})
    _reload_plugins(request)
    return {"ok": True, "result": result}


@router.patch("/plugins/{plugin_id}")
def toggle_plugin(request: Request, plugin_id: str,
                   payload: dict[str, Any] = Body(default={})) -> dict:
    enabled = bool(payload.get("enabled", True))
    _store(request).set_enabled(plugin_id, enabled)
    return {"ok": True, "id": plugin_id, "enabled": enabled}


def _cookie_names(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("cookies") if isinstance(data, dict) and "cookies" in data else data
    if isinstance(raw, dict):          # {name: value}
        return list(raw.keys())
    if isinstance(raw, list):          # [{name, value, ...}]
        return [str(c.get("name")) for c in raw if isinstance(c, dict) and c.get("name")]
    return []


def _login_flow_hint() -> str:
    window = "、".join(str(s["label"]) for s in auth_mod.SPECS.values())
    cli = "、".join(str(s["label"]) for s in auth_mod.CLI_SPECS.values())
    return f"有内置登录窗口的平台：{window}；{cli} 用 CLI 登录"


@router.get("/auth")
def auth_rows() -> dict:
    """设置页「登录态」的行清单：后端有哪些登录流程，前端就画哪些行。"""
    rows = [auth_mod.describe(pid) for pid in (*auth_mod.SPECS, *auth_mod.CLI_SPECS)]
    return {"rows": rows}


@router.get("/auth/{plugin_id}")
def auth(request: Request, plugin_id: str) -> dict:
    """登录四态：not_required / available / need_login / error。"""
    info = auth_mod.describe(plugin_id)
    spec = auth_mod.SPECS.get(plugin_id)
    if spec is None:
        # CLI 管的（B 站）或根本不需要登录的平台：如实说清楚，不给假按钮
        return {**info, "state": "not_required",
                "message": auth_mod.CLI_SPECS.get(plugin_id, {}).get("hint", "这个平台不需要登录")}

    path = state_root() / "cookies" / f"{plugin_id}.json"
    window = auth_mod.session_state(plugin_id)
    if window in ("opened", "waiting"):
        return {**info, "state": "need_login", "window": window,
                "message": f"{spec['label']}登录窗口开着，扫完会自动检测",
                "hint": ""}
    if not path.exists():
        return {**info, "state": "need_login",
                "message": f"{spec['label']}还没登录",
                "hint": "点「打开登录窗口」，在弹出来的 Chrome 里扫码；登录完回到这里点「我已完成登录」"}
    names = _cookie_names(path)
    ok = any(n.lower() in {c.lower() for c in spec["cookies"]} for n in names)
    if not ok:
        return {**info, "state": "need_login",
                "message": f"cookie 文件在，但里面没有 {spec['cookies'][0]}",
                "hint": "重新走一遍登录窗口；只放一个不完整的 cookie 文件不行"}
    return {**info, "state": "available", "message": f"已登录（{len(names)} 个 cookie）",
            "hint": "", "cookies": len(names), "saved_at": path.stat().st_mtime}


@router.post("/auth/{plugin_id}/login")
def auth_login(plugin_id: str) -> dict:
    try:
        result = auth_mod.start(plugin_id)
    except KeyError:
        raise HTTPException(status_code=400, detail={
            "code": "no_login_flow", "message": f"{plugin_id} 没有内置登录流程",
            "hint": _login_flow_hint()})
    except Exception as exc:
        raise HTTPException(status_code=500, detail={
            "code": "login_failed", "message": f"{type(exc).__name__}: {exc}"[:300],
            "hint": "关掉登录窗口重试；还不行就检查本机有没有 Chrome"})
    return {"ok": True, "login": result}


@router.get("/auth/{plugin_id}/login/status")
def auth_login_status(plugin_id: str) -> dict:
    try:
        return auth_mod.check(plugin_id)
    except KeyError:
        raise HTTPException(status_code=400, detail={
            "code": "no_login_flow", "message": f"{plugin_id} 没有内置登录流程",
            "hint": _login_flow_hint()})


@router.post("/auth/{plugin_id}/logout")
def auth_logout(plugin_id: str) -> dict:
    try:
        result = auth_mod.logout(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "bad_plugin_id", "message": str(exc)[:200],
            "hint": "插件 id 只能是单层目录名，不能带路径分隔符、盘符或 NUL"})
    except KeyError:
        raise HTTPException(status_code=400, detail={
            "code": "no_login_flow", "message": f"{plugin_id} 没有内置登录流程",
            "hint": _login_flow_hint()})
    return {"ok": True, **result}


@router.get("/runs")
def runs(request: Request, limit: int = Query(20, ge=1, le=100)) -> dict:
    return {"runs": _store(request).recent_runs(limit)}