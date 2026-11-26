"""插件能力层的网络边界回归。

跑法：
    python tests/test_capabilities.py
只测纯函数：公网 URL 判定与重定向逐跳校验，不启动浏览器、不发真实请求。
"""
from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_runtime import capabilities  # noqa: E402
from plugin_runtime.capabilities import Capabilities, _GuardedRedirect, _is_public_http  # noqa: E402
from plugin_runtime.manifest import APP_TOKEN, STATE_TOKEN, validate_manifest  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def test_blocks_private_targets() -> None:
    for url in (
        "http://127.0.0.1/",
        "http://127.0.0.1:8790/api/health",
        "https://localhost/",
        "http://foo.localhost/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://1.1.1.1/",
        "http://user:pass@1.1.1.1/",
        "http://0.0.0.0/",
    ):
        check(not _is_public_http(url), f"拒绝 {url}")


def test_allows_public_literal() -> None:
    check(_is_public_http("https://1.1.1.1/"), "放行公网 https 字面量")
    check(_is_public_http("http://1.1.1.1:80/x"), "放行公网 http 字面量")


def test_dns_failure_is_closed() -> None:
    with patch("plugin_runtime.capabilities.socket.getaddrinfo", side_effect=OSError("no dns")):
        check(not _is_public_http("https://no-such-host.invalid/"),
              "解析失败按拒绝处理，不把请求交给下一层")


def test_redirect_guard_blocks_private() -> None:
    req = SimpleNamespace(full_url="https://1.1.1.1/start")
    try:
        _GuardedRedirect().redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/secret")
    except PermissionError:
        check(True, "302 跳到 127.0.0.1 被拦下")
    else:
        check(False, "302 跳到 127.0.0.1 应被拦下")


def test_http_redirect_is_rechecked() -> None:
    """直连公网 URL 后被 302 到内网时，_http 必须在发第二跳前失败。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/secret")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"secret")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = capabilities._is_public_http

    def allow_only_start(url: str) -> bool:
        return url.endswith("/start") or original(url)

    capabilities._is_public_http = allow_only_start
    try:
        cap = object.__new__(Capabilities)
        cap.manifest = SimpleNamespace(id="test")
        cap.settings = {}
        cap.demo = False
        cap._logger = lambda level, message: None
        try:
            cap._http({"url": f"http://127.0.0.1:{server.server_port}/start"})
        except PermissionError as exc:
            check("拒绝跳转" in str(exc), "重定向目标被公网校验拦下")
        else:
            check(False, "重定向目标应被拦下")
    finally:
        capabilities._is_public_http = original
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _base_manifest() -> dict:
    return {
        "schemaVersion": 1,
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "capabilities": ["cli"],
        "kinds": ["short"],
        "feeds": [{"id": "main", "name": "Main"}],
        "entry": "index.js",
    }


def test_manifest_seed_boundaries() -> None:
    data = _base_manifest()
    data["cli"] = {
        "allow": [["bili", "feed"]],
        "seed": [{"from": APP_TOKEN + "/bili/credential.json",
                  "to": STATE_TOKEN + "/toolhome/credential.json"}],
    }
    check(validate_manifest(data) == [], "官方形态的 seed 可以通过")

    bad_to = _base_manifest()
    bad_to["cli"] = {
        "allow": [["bili"]],
        "seed": [{"from": APP_TOKEN + "/bili/credential.json",
                  "to": STATE_TOKEN + "/../escape.json"}],
    }
    errors = validate_manifest(bad_to)
    check(any("seed.to" in e and ".." in e for e in errors), "seed.to 含 .. 被拒绝")

    bad_from = _base_manifest()
    bad_from["cli"] = {
        "allow": [["bili"]],
        "seed": [{"from": "C:\\\\Windows\\\\win.ini", "to": STATE_TOKEN + "/x"}],
    }
    errors = validate_manifest(bad_from)
    check(any("seed.from" in e for e in errors), "seed.from 指向系统目录被拒绝")


def test_manifest_command_and_env_boundaries() -> None:
    bad_cmd = _base_manifest()
    bad_cmd["cli"] = {"allow": [["python", "-c", "print(1)"]]}
    errors = validate_manifest(bad_cmd)
    check(any("解释器" in e for e in errors), "cli.allow 拒绝 python")

    bad_env = _base_manifest()
    bad_env["cli"] = {"allow": [["bili"]], "env": {"PYTHONPATH": "/tmp"}}
    errors = validate_manifest(bad_env)
    check(any("PYTHONPATH" in e for e in errors), "cli.env 拒绝 PYTHONPATH")

    bad_setting = _base_manifest()
    bad_setting["settings"] = [{"key": "cookieFile", "default": "C:\\\\secret.json"}]
    errors = validate_manifest(bad_setting)
    check(any("cookieFile" in e for e in errors), "cookieFile 默认值必须在 state 下")


def test_runtime_paths_are_confined() -> None:
    root = capabilities.state_root().resolve()
    token = capabilities._STATE_TOKEN
    check(capabilities._state_path(token + "/ok", "demo", "test") == root / "ok",
          "state 内路径放行")
    for bad in (token + "/../escape", token + "/..", str(root.parent / "escape")):
        try:
            capabilities._state_path(bad, "demo", "test")
        except PermissionError:
            check(True, f"state 外路径被拒绝：{bad}")
        else:
            check(False, f"state 外路径应被拒绝：{bad}")

    check(capabilities._seed_source_path(token + "/seed.json", "demo") == root / "seed.json",
          "seed 源允许 state 内文件")
    try:
        capabilities._seed_source_path("C:\\\\Windows\\\\win.ini", "demo")
    except PermissionError:
        check(True, "seed 源拒绝系统目录")
    else:
        check(False, "seed 源应拒绝系统目录")


def main() -> int:
    try:
        test_blocks_private_targets()
        test_allows_public_literal()
        test_dns_failure_is_closed()
        test_redirect_guard_blocks_private()
        test_http_redirect_is_rechecked()
        test_manifest_seed_boundaries()
        test_manifest_command_and_env_boundaries()
        test_runtime_paths_are_confined()
    except AssertionError as exc:
        print(f"FAIL {exc}")
        return 1
    print(f"PASS {CHECKS} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())