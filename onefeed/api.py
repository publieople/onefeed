"""HTTP 路由（003 T30–T45）。

只读信息流 + 刷新编排 + 插件市场 + 登录状态。错误统一 {error:{code,message,hint}}。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from . import __version__, market, smart
from .service import RefreshRunner, demo_mode
from .store import SORTS, Store

router = APIRouter(prefix="/api")


def _store(request: Request) -> Store:
    return request.app.state.store


def _runner(request: Request) -> RefreshRunner:
    return request.app.state.refresher


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


@router.post("/refresh", status_code=202)
def refresh(request: Request, payload: dict[str, Any] = Body(default={})) -> dict:
    platforms = payload.get("platforms") if isinstance(payload, dict) else None
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
    installed = store.list_plugins()
    return {"installed": installed, "market": market.merged(store, force=refresh_market)}


@router.post("/plugins/{plugin_id}/install")
def install_plugin(request: Request, plugin_id: str) -> dict:
    store = _store(request)
    try:
        result = market.install(store, plugin_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={
            "code": "install_failed", "message": f"{type(exc).__name__}: {exc}"[:300],
            "hint": "检查网络、registry 缓存，或改用本地文件安装"})
    _runner(request).host = type(_runner(request).host)()  # 重新发现插件目录
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


AUTH_PROBES = {
    "xiaohongshu": ("id_token", "小红书"),
    "douyin": ("sessionid", "抖音"),
}


@router.get("/auth/{plugin_id}")
def auth(request: Request, plugin_id: str) -> dict:
    """登录四态：not_required / available / need_login / error。"""
    from plugin_runtime.paths import state_root
    probe = AUTH_PROBES.get(plugin_id)
    if not probe:
        return {"plugin": plugin_id, "state": "not_required"}
    cookie_name, label = probe
    path = state_root() / "cookies" / f"{plugin_id}.json"
    if not path.exists():
        return {"plugin": plugin_id, "state": "need_login",
                "message": f"{label}还没登录", "hint": "在设置页点登录，或把 cookie 放到 "
                f"{path}"}
    try:
        import json as _json
        data = _json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"plugin": plugin_id, "state": "error", "message": f"cookie 读不出来：{exc}"}
    raw = data.get("cookies") if isinstance(data, dict) and "cookies" in data else data
    names: list[str] = []
    if isinstance(raw, dict):          # {name: value}
        names = list(raw.keys())
    elif isinstance(raw, list):        # [{name, value, ...}]
        names = [str(c.get("name")) for c in raw if isinstance(c, dict) and c.get("name")]
    ok = any(n.lower() == cookie_name for n in names)
    return {"plugin": plugin_id, "state": "available" if ok else "need_login",
            "message": "已登录" if ok else f"cookie 里没有 {cookie_name}",
            "hint": "" if ok else f"重新扫码，或补上 {cookie_name}"}


@router.get("/runs")
def runs(request: Request, limit: int = Query(20, ge=1, le=100)) -> dict:
    return {"runs": _store(request).recent_runs(limit)}
