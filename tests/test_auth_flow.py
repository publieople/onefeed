"""登录窗口的 cookie 判据（不真的开浏览器，用假的 context）。"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from onefeed import auth  # noqa: E402
from plugin_runtime.paths import state_root  # noqa: E402


class FakeCtx:
    """只需 cookies() / pages / close()：_poll 只用到这三样。"""

    def __init__(self, cookies, close_error=None):
        self._cookies = cookies
        self.pages = []
        self.closed = False
        self._close_error = close_error

    def cookies(self):
        if self._close_error is not None:
            raise RuntimeError(self._close_error)
        return self._cookies

    def close(self):
        self.closed = True


def _cookie(name, value="1", domain=".douyin.com"):
    return {"name": name, "value": value, "domain": domain, "path": "/",
            "expires": -1, "httpOnly": False, "secure": True, "sameSite": "Lax"}


def case_wait_then_ok():
    """游客 cookie 先返回一次，第二次带上 sessionid → state=ok 且落盘。"""
    path = state_root() / "cookies" / "douyin.json"
    if path.exists():
        path.unlink()

    class Ctx(FakeCtx):
        def __init__(self):
            super().__init__([_cookie("ttwid")])
            self.round = 0

        def cookies(self):
            self.round += 1
            if self.round == 1:
                return [_cookie("ttwid")]
            return [_cookie("ttwid"), _cookie("sessionid", "abc"), _cookie("x", "1", ".douyin.com")]

    session = auth._Session("douyin", auth.SPECS["douyin"])
    session.state = "waiting"     # _run 调 _poll 之前就是这么置的
    session.ready.set()
    session._poll(Ctx())
    assert session.state == "ok", session.state
    assert session.cookie == "sessionid", session.cookie
    assert session.cookies == 3, session.cookies
    data = json.loads(path.read_text(encoding="utf-8"))
    names = [c["name"] for c in data["cookies"]]
    assert names == ["ttwid", "sessionid", "x"], names
    assert data["plugin"] == "douyin"
    assert data["source"] == "browser-login"
    path.unlink()
    print("case_wait_then_ok ok")


def case_scoped_by_domain():
    """别的域名的 cookie 不算（.douyinstatic.com 上的也带 douyin 字样，但域名要 endswith .douyin.com）。"""
    class Ctx(FakeCtx):
        def __init__(self):
            super().__init__([_cookie("sessionid", "1", ".douyinstatic.com")])

    session = auth._Session("douyin", auth.SPECS["douyin"])
    session.state = "waiting"     # _run 调 _poll 之前就是这么置的
    session.ready.set()
    worker = threading.Thread(target=session._poll, args=(Ctx(),), daemon=True)
    worker.start()
    time.sleep(1.2)                 # 让它转一轮
    session.stop.set()              # 模拟 logout
    worker.join(5.0)
    assert session.state == "waiting", session.state
    assert session.cookies == 0, session.cookies
    assert not (state_root() / "cookies" / "douyin.json").exists()
    print("case_scoped_by_domain ok")


def case_window_closed():
    """用户在窗口里点了叉 → closed，而不是 error。"""
    class Ctx(FakeCtx):
        def __init__(self):
            super().__init__([], close_error="Target page, context or browser has been closed")

    session = auth._Session("douyin", auth.SPECS["douyin"])
    session.state = "waiting"     # _run 调 _poll 之前就是这么置的
    session.ready.set()
    session._poll(Ctx())
    assert session.state == "closed", session.state
    print("case_window_closed ok")


def case_stop_flag():
    """logout 把 stop 置上后，轮询立刻退出，不会拖 10 分钟。"""
    class Ctx(FakeCtx):
        def __init__(self):
            super().__init__([_cookie("ttwid")])

    session = auth._Session("douyin", auth.SPECS["douyin"])
    session.state = "waiting"     # _run 调 _poll 之前就是这么置的
    session.ready.set()
    session.stop.set()
    session._poll(Ctx())
    assert session.state == "waiting", session.state
    print("case_stop_flag ok")


def case_cookie_names_reads_file():
    path = state_root() / "cookies" / "douyin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cookies": [{"name": "sessionid"}, {"name": "ttwid"}]}), encoding="utf-8")
    assert auth._cookie_names("douyin") == ["sessionid", "ttwid"]
    path.write_text(json.dumps({"sessionid": "1", "ttwid": "2"}), encoding="utf-8")
    assert sorted(auth._cookie_names("douyin")) == ["sessionid", "ttwid"]
    path.unlink()
    assert auth._cookie_names("douyin") == []
    print("case_cookie_names_reads_file ok")


def main() -> int:
    cases = [case_wait_then_ok, case_scoped_by_domain, case_window_closed,
             case_stop_flag, case_cookie_names_reads_file]
    for case in cases:
        case()
    print(f"test_auth_flow: {len(cases)} cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())