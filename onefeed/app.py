"""FastAPI 应用（003 T30）。

一个进程同时干两件事：托管前端静态文件、提供 /api。
绑定地址由入口 __main__ 控制，这里默认只给 127.0.0.1。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import router
from .store import Store

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="OneFeed", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json")
    app.state.store = store or Store()

    app.include_router(router)
    _install_error_handlers(app)
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
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
