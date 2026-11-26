"""本地 API 的 Host 与 CSRF 防护。

OneFeed 只监听本机，但浏览器里的任意网页都能向 127.0.0.1 发简单请求。
这里做两道闸：

- Host 只接受 localhost / testserver / IP 字面量（可用 ONEFEED_ALLOWED_HOSTS
  追加自定义主机名）。防的是 DNS rebinding：攻击者把自己的域名解析到 127.0.0.1，
  浏览器发来的 Host 仍是攻击者域名。
- 写操作（POST/PUT/PATCH/DELETE）如果带 Origin/Referer，必须和请求同源；
  Origin: null 与 Sec-Fetch-Site: cross-site 一律拒绝。没有 Origin/Referer 的
  请求（CLI、TestClient、curl）放行，避免把非浏览器客户端一起挡掉。
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LOOPBACK_HOSTS = {"localhost", "testserver"}


def _extra_hosts() -> set[str]:
    raw = os.environ.get("ONEFEED_ALLOWED_HOSTS", "")
    return {part.strip().lower().rstrip(".") for part in raw.split(",") if part.strip()}


def _hostname(host_header: str) -> str | None:
    try:
        parsed = urlsplit("//" + host_header.strip())
        _ = parsed.port            # 端口非法时这里会抛 ValueError
        name = parsed.hostname
    except ValueError:
        return None
    return name.lower().rstrip(".") if name else None


def host_allowed(host_header: str) -> bool:
    name = _hostname(host_header)
    if not name:
        return False
    if name in _LOOPBACK_HOSTS or name in _extra_hosts():
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if not parsed.scheme or not parsed.hostname:
            return None
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    return parsed.scheme.lower(), parsed.hostname.lower().rstrip("."), port


def _same_origin(value: str, request: Request) -> bool:
    expected = _origin_tuple(f"{request.url.scheme}://{request.headers.get('host', '')}")
    actual = _origin_tuple(value)
    return expected is not None and actual is not None and expected == actual


def origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin:
        return origin.strip().lower() != "null" and _same_origin(origin, request)
    referer = request.headers.get("referer")
    if referer:
        return _same_origin(referer, request)
    return (request.headers.get("sec-fetch-site") or "").strip().lower() not in {
        "cross-site", "same-site",
    }


def install_local_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def _guard(request: Request, call_next):
        if not host_allowed(request.headers.get("host", "")):
            return JSONResponse(status_code=403, content={"error": {
                "code": "forbidden_host",
                "message": "Host 不是本机地址",
                "hint": "只从 localhost / 127.0.0.1 访问；自定义域名请设置 ONEFEED_ALLOWED_HOSTS",
            }})
        if request.method.upper() not in _SAFE_METHODS and not origin_allowed(request):
            return JSONResponse(status_code=403, content={"error": {
                "code": "forbidden_origin",
                "message": "写操作必须来自同源页面",
                "hint": "跨站页面不能触发 OneFeed 的写操作；请从本地页面重试",
            }})
        return await call_next(request)
