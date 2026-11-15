"""FastAPI 应用（003 T30）。

一个进程同时干两件事：托管前端静态文件、提供 /api。
绑定地址由入口 __main__ 控制，这里默认只给 127.0.0.1。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from plugin_runtime.host import PluginHost

from . import __version__, settings as settings_mod
from .api import router
from .service import RefreshRunner, sync_installed
from .store import Store

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="OneFeed", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json")
    app.state.store = store or Store()
    conf = settings_mod.load()
    app.state.settings = conf
    plugins_dir = settings_mod.resolve_plugins_dir(conf.get("plugins_dir", ""))
    sync_installed(app.state.store, plugins_dir)
    app.state.refresher = RefreshRunner(
        app.state.store,
        host=PluginHost(plugins_dir=plugins_dir),
        limit=int(conf.get("per_plugin_limit") or 12),
        prune_days=int(conf.get("prune_days") or 14),
    )

    app.include_router(router)
    _install_error_handlers(app)
    if WEB_DIST.is_dir():
        assets = WEB_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}")
        def _spa(full_path: str) -> FileResponse:
            """单页应用兜底：/market、/settings 这些前端路由都回 index.html。"""
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            candidate = (WEB_DIST / full_path).resolve()
            if full_path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")
    else:
        @app.get("/")
        def _no_web() -> dict:
            return {"ok": True, "hint": "前端还没构建：在 web/ 下跑 npm run build"}
    return app


def _error(code: str, message: str, hint: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, "hint": hint}})


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return _error(detail["code"], detail.get("message", ""), detail.get("hint", ""),
                          exc.status_code)
        return _error("http_error", str(detail), "", exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:]) or "参数"
        return _error("bad_request", f"{field}: {first.get('msg', '参数不合法')}",
                      str(first.get("ctx") or ""), 422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        return _error("internal_error", f"{type(exc).__name__}: {exc}",
                      "看服务端控制台日志", 500)
