"""OF-01 / OF-02 验收：插件 http 能力的出站边界。

跑法：
    python tests/test_plugin_http_guard.py
只管纯函数与能力层拦截：公网判定、声明域白名单、重定向逐跳复检、Cookie 注入范围。
真的发请求在 e2e 里；这里用假 opener，不联网。
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest import mock

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugin_runtime import capabilities  # noqa: E402
from plugin_runtime.manifest import load_manifest, validate_manifest  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0
HOME_DIR = Path(tempfile.mkdtemp(prefix="of-http-guard-"))
os.environ["ONEFEED_HOME"] = str(HOME_DIR)
atexit.register(shutil.rmtree, HOME_DIR, True)


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


class _Man:
    """Capabilities 只用到的清单字段 + setting_defaults()（省得造真目录）。"""

    def __init__(self, **kw):
        self.id = "demo"
        self.capabilities = {"http"}
        self.media_hosts: list[str] = []
        self.http_hosts: list[str] = []
        self.cookie_hosts: list[str] = []
        for key, value in kw.items():
            setattr(self, key, value)

    def setting_defaults(self) -> dict:
        return {}


def manifest(**kw) -> _Man:
    return _Man(**kw)


def caps(man, settings=None) -> capabilities.Capabilities:
    return capabilities.Capabilities(man, settings=settings, logger=lambda *_: None)


def expect_permission(fn, label: str) -> str:
    try:
        fn()
    except PermissionError as exc:
        check(True, label)
        return str(exc)
    raise AssertionError(label + "（没有抛 PermissionError）")


# ---------------------------------------------------------------- 公网判定
def case_public_url_check() -> None:
    check(capabilities._is_public_http("https://api.bilibili.com/x") is True,
          "公网域名放行")
    check(capabilities._is_public_http("http://127.0.0.1:8795/api/settings") is False,
          "回环地址拒绝")
    check(capabilities._is_public_http("http://localhost:8795/") is False,
          "localhost 拒绝")
    check(capabilities._is_public_http("http://192.168.1.10/") is False,
          "内网地址拒绝")
    check(capabilities._is_public_http("file:///C:/Windows/win.ini") is False,
          "非 http(s) 协议拒绝")

    # OF-02 的一半：DNS 解析不了时必须 fail-closed（以前 return True 等于放行）
    with mock.patch.object(capabilities.socket, "getaddrinfo", side_effect=OSError("nxdomain")):
        check(capabilities._is_public_http("https://not-resolvable.example/x") is False,
              "DNS 解析失败按拒绝处理（fail-closed）")
    # 解析到内网 IP 的域名（DNS rebinding 的直接形态）也要拒绝
    private = [("", "", "", "", ("10.1.2.3", 0))]
    with mock.patch.object(capabilities.socket, "getaddrinfo", return_value=private):
        check(capabilities._is_public_http("https://rebind.example/x") is False,
              "解析到内网 IP 拒绝")


def case_host_allowed() -> None:
    check(capabilities._host_allowed("api.bilibili.com", ["*.bilibili.com"]) is True,
          "通配符命中子域")
    check(capabilities._host_allowed("bilibili.com", ["*.bilibili.com"]) is False,
          "通配符不匹配裸域（与 media 同语义）")
    check(capabilities._host_allowed("api.example.com", ["api.example.com"]) is True,
          "精确域名命中")
    check(capabilities._host_allowed("evil.example", []) is False,
          "空列表不命中任何域")


# ---------------------------------------------------------------- 重定向
def case_redirect_guard() -> None:
    req = urllib.request.Request(
        "https://api.example.com/x",
        headers={"Cookie": "SESSDATA=secret", "Referer": "https://api.example.com/"},
    )

    # OF-02 的实测形态：首跳合法，302 指到宿主自己的 127.0.0.1
    guard = capabilities._GuardedRedirect(["api.example.com"])
    try:
        guard.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8795/api/settings")
    except capabilities._BlockedRedirect as exc:
        check("127.0.0.1" in str(exc), "302 到回环地址被拦下")
    else:
        raise AssertionError("302 到 127.0.0.1 没有被拦下")

    # 没声明 httpHosts 的插件也要逐跳做公网校验
    guard = capabilities._GuardedRedirect([])
    try:
        guard.redirect_request(req, None, 302, "Found", {}, "http://192.168.1.1/admin")
    except capabilities._BlockedRedirect:
        check(True, "空 httpHosts 时仍拦截内网跳转")
    else:
        raise AssertionError("内网跳转没有被拦下")

    # 下面几条用假公网判定，免得依赖 DNS；公网判定本身在上面的 case 里已经验过
    public = lambda url: "127.0.0.1" not in url and "192.168.1.1" not in url  # noqa: E731
    with mock.patch.object(capabilities, "_is_public_http", side_effect=public):
        # 跨到没声明的公网域：拒绝
        guard = capabilities._GuardedRedirect(["api.example.com"])
        try:
            guard.redirect_request(req, None, 302, "Found", {}, "https://evil.example/collect")
        except capabilities._BlockedRedirect as exc:
            check("未声明" in str(exc), "跳到未声明的公网域被拦下")
        else:
            raise AssertionError("跳到未声明的公网域没有被拦下")

        # 同 host 跳转：Cookie 保留
        guard = capabilities._GuardedRedirect(["api.example.com"])
        same = guard.redirect_request(req, None, 302, "Found", {}, "https://api.example.com/y")
        check(same is not None and same.get_header("Cookie") == "SESSDATA=secret",
              "同 host 跳转保留 Cookie")

        # 换成允许的公网 host：Cookie / Referer 丢掉（别把登录态送出声明域）
        guard = capabilities._GuardedRedirect(["api.example.com", "cdn.example.net"])
        cross = guard.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.net/y")
        check(cross is not None and cross.get_header("Cookie") is None,
              "跨 host 跳转丢掉 Cookie")
        check(cross is not None and cross.get_header("Referer") is None,
              "跨 host 跳转丢掉 Referer")


# ---------------------------------------------------------------- Cookie 范围
def case_cookie_scope() -> None:
    cred = HOME_DIR / "credential.json"
    cred.write_text(json.dumps({"cookies": [{"name": "sessdata", "value": "v1"}]}),
                    encoding="utf-8")

    # OF-01：mediaHosts 里的域可以注（bilibili 的 api.bilibili.com 走这条）
    man = manifest(media_hosts=["*.bilibili.com"])
    headers: dict[str, str] = {}
    caps(man, {"cookieFile": str(cred)})._inject_cookie(
        headers, {"cookieCase": "upper"}, "api.bilibili.com")
    check(headers.get("Cookie") == "SESSDATA=v1", "声明域内注入 Cookie（cookieCase 生效）")

    # 没声明的公网域：拒绝注入
    headers = {}
    err = expect_permission(
        lambda: caps(man, {"cookieFile": str(cred)})._inject_cookie(headers, {}, "evil.example"),
        "未声明域拒绝注入 Cookie")
    check("cookieHosts" in err, "报错里告诉作者用 cookieHosts 声明")
    check("Cookie" not in headers, "拒绝时没有把 Cookie 塞进头")

    # cookieHosts 显式声明时以它为准（不再借用 mediaHosts）
    man = manifest(media_hosts=["*.bilibili.com"], cookie_hosts=["api.example.com"])
    headers = {}
    expect_permission(
        lambda: caps(man, {"cookieFile": str(cred)})._inject_cookie(headers, {}, "api.bilibili.com"),
        "写了 cookieHosts 就不再回退到 mediaHosts")
    headers = {}
    caps(man, {"cookieFile": str(cred)})._inject_cookie(headers, {}, "api.example.com")
    check(headers.get("Cookie") == "sessdata=v1", "cookieHosts 声明的域可以注入")

    # 声明了域但本机没有凭证文件：静默不发，不报错（没登录也能匿名请求）
    headers = {}
    caps(man, {"cookieFile": str(HOME_DIR / "nope.json")})._inject_cookie(
        headers, {}, "api.example.com")
    check("Cookie" not in headers, "凭证文件不存在时不发 Cookie")


# ---------------------------------------------------------------- http 能力拦截
class _FakeResp:
    status = 200
    headers = {"Content-Type": "application/json"}

    def read(self, n: int = -1) -> bytes:
        return b'{"code":0}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    def __init__(self, seen: dict):
        self.seen = seen
        self.requests: list = []

    def open(self, request, timeout=None):
        self.seen.setdefault("requests", []).append(request)
        self.seen["url"] = request.full_url
        return _FakeResp()


def call_http(man, payload: dict, settings=None) -> dict:
    result = caps(man, settings).handle(json.dumps({"cap": "http", **payload}))
    return json.loads(result)


def case_http_capability_guard() -> None:
    man = manifest(http_hosts=["api.example.com"], cookie_hosts=["api.example.com"])
    payload = {"url": "https://api.example.com/x", "credential": "self"}
    settings = {"cookie": "SESSDATA=abc"}
    with mock.patch.object(capabilities.urllib.request, "build_opener",
                           return_value=_FakeOpener({})):
        out = call_http(man, payload, settings)
    check(out["ok"] is True, "声明域内的请求放行")

    # 关闭代理重试：请求成功时不该走第二个代理
    seen: dict = {}
    fake = _FakeOpener(seen)
    def fake_build(*handlers):
        seen["handlers"] = handlers
        return fake
    with mock.patch.object(capabilities.urllib.request, "build_opener", side_effect=fake_build):
        out = call_http(man, payload, settings)
    check(out["ok"] is True, "带声明的请求照常成功")
    check(any(isinstance(h, capabilities._GuardedRedirect) for h in seen["handlers"]),
          "opener 里装了逐跳校验的重定向处理器")
    guard = next(h for h in seen["handlers"] if isinstance(h, capabilities._GuardedRedirect))
    check(guard.allowed_hosts == ["api.example.com"], "重定向处理器带上 httpHosts")
    check(seen["requests"][0].get_header("Cookie") == "SESSDATA=abc",
          "声明域请求带上自己的 Cookie")

    # 未声明的 host：连 opener 都不建
    man2 = manifest(http_hosts=["api.example.com"])
    with mock.patch.object(capabilities.urllib.request, "build_opener",
                           side_effect=AssertionError("不该真的发请求")):
        out = call_http(man2, {"url": "https://evil.example/steal"})
    check(out["ok"] is False and "httpHosts" in out["error"], "未声明 host 的请求被拦下")

    # 有 httpHosts 但没声明 cookieHosts：cookie 只允许去 httpHosts 里的域
    man3 = manifest(http_hosts=["api.example.com"])
    with mock.patch.object(capabilities.urllib.request, "build_opener",
                           return_value=_FakeOpener({})):
        out_ok = call_http(man3, payload, {"cookie": "A=1"})
        out_bad = call_http(man3, {"url": "https://api.example.com/x",
                                   "credential": "self", "headers": {"X-Test": "1"}},
                            {"cookie": "A=1"})
    check(out_ok["ok"] is True and out_bad["ok"] is True,
          "httpHosts 兼作 Cookie 允许域")

    # 一个域都没声明却要 credential:self：拒绝（OF-01 的根因）
    man4 = manifest()
    out = call_http(man4, {"url": "https://evil.example/x", "credential": "self"},
                    {"cookie": "SESSDATA=abc"})
    check(out["ok"] is False and "Cookie" in out["error"],
          "没有声明任何域时拒绝注入 Cookie")

    # 非公网地址仍在第一跳被拦
    with mock.patch.object(capabilities.urllib.request, "build_opener",
                           side_effect=AssertionError("不该真的发请求")):
        out = call_http(man4, {"url": "http://127.0.0.1:8795/api/settings"})
    check(out["ok"] is False and "非公网" in out["error"], "首跳内网地址被拦下")


# ---------------------------------------------------------------- 清单字段
def case_manifest_hosts() -> None:
    errs = validate_manifest({"httpHosts": "api.example.com"})
    check(any("httpHosts 必须是字符串数组" in e for e in errs),
          "httpHosts 类型错报错")
    errs = validate_manifest({"httpHosts": ["https://api.example.com/x"]})
    check(any("不带协议的域名" in e for e in errs), "httpHosts 不接受带协议的 URL")
    errs = validate_manifest({"cookieHosts": [1]})
    check(any("cookieHosts 必须是字符串数组" in e for e in errs),
          "cookieHosts 类型错报错")

    plugin = HOME_DIR / "plugins" / "demo"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "index.js").write_text("// demo\n", encoding="utf-8")
    (plugin / "plugin.json").write_text(json.dumps({
        "schemaVersion": 1, "id": "demo", "name": "Demo", "version": "1.0.0",
        "capabilities": ["http"], "kinds": ["article"],
        "feeds": [{"id": "main", "name": "主"}],
        "httpHosts": ["api.example.com"], "cookieHosts": ["login.example.com"],
    }, ensure_ascii=False), encoding="utf-8")
    man = load_manifest(plugin)
    check(man.http_hosts == ["api.example.com"], "load_manifest 读入 httpHosts")
    check(man.cookie_hosts == ["login.example.com"], "load_manifest 读入 cookieHosts")

    # 没写这两个字段的老插件照常加载（向后兼容）
    (plugin / "plugin.json").write_text(json.dumps({
        "schemaVersion": 1, "id": "demo", "name": "Demo", "version": "1.0.0",
        "capabilities": ["http"], "kinds": ["article"],
        "feeds": [{"id": "main", "name": "主"}],
    }, ensure_ascii=False), encoding="utf-8")
    man = load_manifest(plugin)
    check(man.http_hosts == [] and man.cookie_hosts == [], "老清单没有新字段也能加载")


def main() -> int:
    case_public_url_check()
    case_host_allowed()
    case_redirect_guard()
    case_cookie_scope()
    # 能力层用例用假公网判定：真 DNS 依赖网络，这个仓库的测试默认离线可跑
    public = lambda url: "127.0.0.1" not in url  # noqa: E731
    with mock.patch.object(capabilities, "_is_public_http", side_effect=public):
        case_http_capability_guard()
    case_manifest_hosts()
    print(f"plugin_http_guard ok（{CHECKS} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
