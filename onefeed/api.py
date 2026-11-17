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
from fastapi.responses import StreamingResponse
from plugin_runtime.host import PluginHost
from plugin_runtime.paths import state_root

from . import __version__, auth as auth_mod, market, media as media_mod, smart, settings as settings_mod
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


def _apply_settings(request: Request, conf: dict[str, Any],
                    touched: set[str] | None = None) -> list[str]:
    """把设置落到活着的对象上，返回"这次真正生效了什么"给前端显示。"""
    runner = _runner(request)
    applied: list[str] = []

    limit = int(conf.get("per_plugin_limit") or 12)
    if runner.limit != limit:
        runner.limit = limit
        applied.append(f"每轮条数 → {limit}")

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
        runner.host = PluginHost(plugins_dir=target)
        sync_installed(_store(request), target)
        applied.append(f"插件目录 → {target}")

    if touched and "registry_url" in touched:
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


@router.get("/health")
def health(request: Request) -> dict:
    store = _store(request)
    return {
        "ok": True, "version": __version__, "items": store.count(),
        "db": str(store.path), "plugins": len(store.list_plugins()),
        "platforms": store.platforms(), "demo": demo_mode(),
        "refreshing": _runner(request).running(),
    }


@router.get("/settings")
def get_settings(request: Request) -> dict:
    conf = settings_mod.load()
    plugins_dir = settings_mod.resolve_plugins_dir(str(conf.get("plugins_dir") or ""))
    return {
        "settings": conf,
        "resolved": {"plugins_dir": str(plugins_dir),
                     "registry_url": settings_mod.registry_url(),
                     "state_dir": str(state_root())},
        "defaults": settings_mod.DEFAULTS,
        "sorts": list(settings_mod.SORTS),
    }


@router.put("/settings")
def put_settings(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    try:
        conf = settings_mod.save(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "code": "bad_settings", "message": str(exc),
            "hint": "看 /api/settings 里的 defaults 与允许范围"})
    applied = _apply_settings(request, conf, set(payload or {}))
    return {"ok": True, "settings": conf, "applied": applied,
            "resolved": {"plugins_dir": str(settings_mod.resolve_plugins_dir(
                str(conf.get("plugins_dir") or ""))),
                "registry_url": settings_mod.registry_url()}}


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
                                   cursor=cursor, limit=limit, keyword=keyword, since=since)
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
                "reason": f"{plugin_id} 的插件没有提供评论接口"}

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
                    "reason": f"{plugin_id} 的插件没有提供评论接口"}
        return {"supported": True, "items": [], "count": 0, "next": None,
                "error": message[:300]}

    items = page["items"]
    payload = {"supported": True, "items": items, "count": len(items),
               "limit": limit, "next": page["next"]}
    _COMMENT_CACHE[key] = (now, payload)
    return payload


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
                "reason": f"{plugin_id} 的插件没有提供详情接口"}

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
                    "reason": f"{plugin_id} 的插件没有提供详情接口"}
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

        if not media_mod.SEMAPHORE.acquire(timeout=20):
            raise HTTPException(status_code=503, detail={
                "code": "busy", "message": "同时在拉的视频太多了", "hint": "等一会儿再试"})
        try:
            status, headers, resp = media_mod.open_stream(
                target["url"], referer=target["referer"], cookie=cookie, range_header=range_header)
        except Exception as exc:  # 网络层失败：别把半截流当成功
            media_mod.SEMAPHORE.release()
            raise HTTPException(status_code=502, detail={
                "code": "media_failed", "message": f"取媒体失败：{exc}"[:300],
                "hint": "点原帖试试"})

        if status < 400:
            break

        try:
            resp.close()
        finally:
            media_mod.SEMAPHORE.release()

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
    out["cache-control"] = "private, max-age=0"

    def _body():
        try:
            yield from media_mod.iter_body(resp)
        finally:
            media_mod.SEMAPHORE.release()

    return StreamingResponse(_body(), status_code=status, headers=out,
                             media_type=headers.get("content-type", "application/octet-stream"))


@router.post("/refresh", status_code=202)
def refresh(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    platforms = payload.get("platforms") if isinstance(payload, dict) else None
    _COMMENT_CACHE.clear()  # 新一轮采集后评论可能变了，别拿旧缓存糊弄
    started, state = _runner(request).trigger(platforms=platforms)
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
    conf = settings_mod.load()
    target = settings_mod.resolve_plugins_dir(str(conf.get("plugins_dir") or ""))
    _runner(request).host = PluginHost(plugins_dir=target)  # 重新发现插件目录
    sync_installed(store, target)
    return {"ok": True, "result": result}


def _reload_plugins(request: Request) -> None:
    """装/更新/卸载之后重新发现插件目录：目录是事实，库只是索引。"""
    store = _store(request)
    conf = settings_mod.load()
    target = settings_mod.resolve_plugins_dir(str(conf.get("plugins_dir") or ""))
    _runner(request).host = PluginHost(plugins_dir=target)
    sync_installed(store, target)


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
            "hint": "确认插件目录存在并且进程有删除权限"})
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
            "hint": "只有小红书、抖音需要登录；B 站用 bili CLI"})
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
            "hint": "只有小红书、抖音需要登录"})


@router.post("/auth/{plugin_id}/logout")
def auth_logout(plugin_id: str) -> dict:
    try:
        result = auth_mod.logout(plugin_id)
    except KeyError:
        raise HTTPException(status_code=400, detail={
            "code": "no_login_flow", "message": f"{plugin_id} 没有内置登录流程",
            "hint": "只有小红书、抖音需要登录"})
    return {"ok": True, **result}


@router.get("/runs")
def runs(request: Request, limit: int = Query(20, ge=1, le=100)) -> dict:
    return {"runs": _store(request).recent_runs(limit)}