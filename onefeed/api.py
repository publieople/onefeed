"""HTTP 路由（003 T30–T45）。

只读信息流 + 刷新编排 + 插件市场 + 登录状态。错误统一 {error:{code,message,hint}}。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from plugin_runtime.host import PluginHost
from plugin_runtime.paths import state_root

from . import __version__, auth as auth_mod, market, smart, settings as settings_mod
from .service import RefreshRunner, demo_mode, sync_installed
from .store import SORTS, Store

router = APIRouter(prefix="/api")

# 评论不像信息流那样每分钟在变，缓存十分钟，省掉反复起子进程的开销。
_COMMENT_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
COMMENT_TTL = 600


def _store(request: Request) -> Store:
    return request.app.state.store


def _runner(request: Request) -> RefreshRunner:
    return request.app.state.refresher


def _apply_settings(request: Request, conf: dict[str, Any]) -> list[str]:
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

    target = settings_mod.resolve_plugins_dir(str(conf.get("plugins_dir") or ""))
    current_dir = Path(str(getattr(runner.host, "plugins_dir", "") or ".")).resolve()
    if current_dir != target.resolve():
        runner.host = PluginHost(plugins_dir=target)
        sync_installed(_store(request), target)
        applied.append(f"插件目录 → {target}")

    applied.append(f"registry → {settings_mod.registry_url()}")
    return applied


def _percentiles(store: Store, rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """每条内容在本平台内的热度分位（前 xx%）。跨平台不能直比热度，只能比名次。"""
    out: dict[str, dict[str, int]] = {}
    for platform in {r["platform"] for r in rows}:
        values = [int(v) for (v,) in store.conn.execute(
            "SELECT like_count FROM items WHERE platform = ?", (platform,)).fetchall()]
        total = len(values) or 1
        for row in rows:
            if row["platform"] != platform:
                continue
            value = int(row.get("like_count") or 0)
            if value <= 0:
                continue  # 没有互动数据就别编名次
            better = sum(1 for v in values if v > value)
            pct = max(1, round((better + 1) * 100 / total))
            if pct <= 50:  # 只有真的靠前才值得说
                out.setdefault(platform, {})[row["id"]] = pct
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
    applied = _apply_settings(request, conf)
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
    if row.get("cluster_id"):
        sib_rows = store.conn.execute(
            "SELECT id, platform, title, author, url, published_at FROM items "
            "WHERE cluster_id = ? AND id != ? ORDER BY platform", (row["cluster_id"], item_id)
        ).fetchall()
        siblings = [dict(r) for r in sib_rows]
    return {"item": row, "siblings": siblings}


@router.get("/item/{item_id}/comments")
def item_comments(request: Request, item_id: str, limit: int = Query(20, ge=1, le=50),
                  refresh: bool = Query(False)) -> dict:
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
                "reason": f"{plugin_id} 的插件没有提供评论接口",
                "hint": "评论要看平台接口好不好拿；拿不到的插件就不做，卡片和详情照常看"}

    key = (item_id, limit)
    now = time.time()
    cached = _COMMENT_CACHE.get(key)
    if cached and not refresh and now - cached[0] < COMMENT_TTL:
        return {**cached[1], "from_cache": True}

    try:
        items = host.comments(plugin_id, row, limit=limit)
    except RuntimeError as exc:
        message = str(exc)
        if "插件未实现" in message:
            return {"supported": False, "items": [], "count": 0,
                    "reason": f"{plugin_id} 的插件没有提供评论接口"}
        return {"supported": True, "items": [], "count": 0,
                "error": message[:300],
                "hint": "评论接口失败不影响看内容；多半是没登录或平台限流"}

    payload = {"supported": True, "items": items, "count": len(items), "limit": limit}
    _COMMENT_CACHE[key] = (now, payload)
    return payload


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
