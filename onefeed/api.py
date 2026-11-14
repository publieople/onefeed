"""HTTP 路由（003 T30）。

只读 API 先做三件：信息流分页、单条详情、健康检查。
错误统一 {error: {code, message, hint}}，HTTP 状态码用真的，不用 200 包错误。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from . import __version__
from .store import SORTS, Store

router = APIRouter(prefix="/api")


def _store(request: Request) -> Store:
    return request.app.state.store


@router.get("/health")
def health(request: Request) -> dict:
    store = _store(request)
    return {
        "ok": True,
        "version": __version__,
        "items": store.count(),
        "db": str(store.path),
        "plugins": len(store.list_plugins()),
        "platforms": store.platforms(),
    }


@router.get("/feed")
def feed(
    request: Request,
    platform: str | None = Query(None, description="逗号分隔，例：bilibili,xiaohongshu"),
    kind: str | None = Query(None, description="video / images / article / short / list"),
    sort: str = Query("freshness"),
    cursor: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail={
            "code": "bad_sort",
            "message": f"不支持的排序：{sort}",
            "hint": f"可选：{', '.join(SORTS)}",
        })
    platforms = [p.strip() for p in platform.split(",") if p.strip()] if platform else None
    rows, next_cursor = _store(request).page(
        platforms=platforms, kind=kind, sort=sort, cursor=cursor, limit=limit)
    return {"items": rows, "next": next_cursor, "count": len(rows)}


@router.get("/item/{item_id}")
def item(request: Request, item_id: str) -> dict:
    row = _store(request).get_item(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail={
            "code": "item_not_found",
            "message": f"没有这条内容：{item_id}",
            "hint": "id 形如 <插件 id>:<平台原生 id>，可从 /api/feed 的返回里取",
        })
    return {"item": row}


@router.get("/plugins")
def plugins(request: Request) -> dict:
    """已安装插件（T38 会补上 registry 的可用列表）。"""
    return {"installed": _store(request).list_plugins()}


@router.get("/runs")
def runs(request: Request, limit: int = Query(20, ge=1, le=100)) -> dict:
    return {"runs": _store(request).recent_runs(limit)}
