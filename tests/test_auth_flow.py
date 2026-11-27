"""登录窗口的 cookie 判据（不真的开浏览器，用假的 context）。"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 登录态文件为测试临时目录，避免跑测试时覆盖/删除本机真实 cookie。
_TEST_HOME = tempfile.mkdtemp(prefix="onefeed-auth-flow-")
atexit.register(shutil.rmtree, _TEST_HOME, ignore_errors=True)
os.environ["ONEFEED_HOME"] = _TEST_HOME

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


class FakePage:
    """CDP 标签页：只测 _poll 的关页判断，不需要真的导航。"""

    def __init__(self, closed=True):
        self._closed = closed
        self.url = "https://www.douyin.com/"

    def is_closed(self):
        return self._closed

    def bring_to_front(self):
        pass

    def goto(self, *args, **kwargs):
        pass


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


def case_cdp_tab_closed_while_context_alive():
    """CDP 下关的是标签页，context 活着、cookies() 不抛错，也要立刻判 closed。"""
    class Ctx(FakeCtx):
        def __init__(self):
            super().__init__([_cookie("ttwid")])

    session = auth._Session("douyin", auth.SPECS["douyin"])
    session.state = "waiting"
    session.ready.set()
    with mock.patch.object(auth, "MAX_WAIT_SEC", 1):
        session._poll(Ctx(), FakePage(closed=True))
    assert session.state == "closed", session.state
    assert "关掉" in session.message, session.message
    print("case_cdp_tab_closed_while_context_alive ok")


def case_logout_sidecar_down_keeps_profile_message():
    """sidecar 没运行时不能谎报“专用 Chrome 的 cookie 都清了”。"""
    old_cdp = os.environ.get("ONEFEED_BROWSER_CDP")
    old_profile = os.environ.get("ONEFEED_BROWSER_PROFILE")
    cookie_path = state_root() / "cookies" / "douyin.json"
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text(json.dumps({"cookies": [{"name": "sessionid"}]}), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="onefeed-logout-test-") as td:
        os.environ["ONEFEED_BROWSER_CDP"] = "http://127.0.0.1:9223"
        os.environ["ONEFEED_BROWSER_PROFILE"] = td
        try:
            with patch.object(auth.browser_cdp, "clear_cookies", return_value=False), \
                    patch.object(auth.browser_cdp, "alive", return_value=False):
                result = auth.logout("douyin")
            assert "专用 Chrome 没在运行" in result["message"], result["message"]
            assert "都清了" not in result["message"], result["message"]
            assert not cookie_path.exists(), "cookie 状态文件应被删掉"
        finally:
            if old_cdp is None:
                os.environ.pop("ONEFEED_BROWSER_CDP", None)
            else:
                os.environ["ONEFEED_BROWSER_CDP"] = old_cdp
            if old_profile is None:
                os.environ.pop("ONEFEED_BROWSER_PROFILE", None)
            else:
                os.environ["ONEFEED_BROWSER_PROFILE"] = old_profile
            cookie_path.unlink(missing_ok=True)
    print("case_logout_sidecar_down_keeps_profile_message ok")


def case_default_logout_does_not_claim_profile_removed():
    """默认分支 rmtree 失败时，不能把「只删了 cookie 文件」说成 profile 也删了。"""
    old_cdp = os.environ.get("ONEFEED_BROWSER_CDP")
    os.environ.pop("ONEFEED_BROWSER_CDP", None)
    with tempfile.TemporaryDirectory(prefix="onefeed-logout-default-"):
        # 默认分支看的是 state_root()/login/<plugin>，不是 CDP 的 profile 目录。
        profile = state_root() / "login" / "douyin"
        profile.mkdir(parents=True, exist_ok=True)
        cookie_path = state_root() / "cookies" / "douyin.json"
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_path.write_text(json.dumps({"cookies": [{"name": "sessionid"}]}), encoding="utf-8")
        try:
            with mock.patch.object(auth.shutil, "rmtree", side_effect=OSError("busy")):
                result = auth.logout("douyin")
            assert "profile 没删掉" in result["message"], result["message"]
            assert "都删了" not in result["message"], result["message"]
        finally:
            if old_cdp is None:
                os.environ.pop("ONEFEED_BROWSER_CDP", None)
            else:
                os.environ["ONEFEED_BROWSER_CDP"] = old_cdp
            cookie_path.unlink(missing_ok=True)
    print("case_default_logout_does_not_claim_profile_removed ok")


def case_cdp_clear_failure_is_not_no_cookie():
    """Chrome 还开着、清理抛异常时，不能说成「本来就没登录」。"""
    old_cdp = os.environ.get("ONEFEED_BROWSER_CDP")
    with tempfile.TemporaryDirectory(prefix="onefeed-logout-fail-") as td:
        os.environ["ONEFEED_BROWSER_CDP"] = "http://127.0.0.1:9223"
        try:
            with mock.patch.object(auth.browser_cdp, "clear_cookies", return_value=None), \
                    mock.patch.object(auth.browser_cdp, "alive", return_value=True), \
                    mock.patch.object(auth.browser_cdp, "profile_dir", return_value=Path(td)):
                result = auth.logout("douyin")
            assert "清理时出错" in result["message"], result["message"]
            assert "本来就没有登录态" not in result["message"], result["message"]
        finally:
            if old_cdp is None:
                os.environ.pop("ONEFEED_BROWSER_CDP", None)
            else:
                os.environ["ONEFEED_BROWSER_CDP"] = old_cdp
    print("case_cdp_clear_failure_is_not_no_cookie ok")


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


def case_bili_cookie_syncs_to_cli():
    """B 站扫码拿到的大写 cookie 要写成 bili CLI 认识的小写 credential.json。"""
    with tempfile.TemporaryDirectory() as td:
        cookie_path = Path(td) / "cookies" / "bilibili.json"
        cred_path = Path(td) / "toolhome" / "bili-cli" / "credential.json"
        cookies = [
            _cookie("SESSDATA", "abc", ".bilibili.com"),
            _cookie("bili_jct", "jct", ".bilibili.com"),
            _cookie("DedeUserID", "42", ".bilibili.com"),
            _cookie("buvid3", "b3", ".bilibili.com"),
            _cookie("buvid4", "b4", ".bilibili.com"),
        ]
        with patch.object(auth, "_cookie_path", return_value=cookie_path):
            with patch.object(auth, "_bili_credential_path", return_value=cred_path):
                session = auth._Session("bilibili", auth.SPECS["bilibili"])
                session.state = "waiting"
                session.ready.set()
                session._poll(FakeCtx(cookies))
                assert auth.bili_credential_ready() is True
        assert session.state == "ok", session.state
        assert "B 站凭证已同步" in session.message, session.message
        data = json.loads(cred_path.read_text(encoding="utf-8"))
        assert data["sessdata"] == "abc", data
        assert data["bili_jct"] == "jct", data
        assert data["dedeuserid"] == "42", data
        assert data["buvid3"] == "b3", data
        assert data["buvid4"] == "b4", data
        assert data["ac_time_value"] is None, data
    print("case_bili_cookie_syncs_to_cli ok")


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
             case_cdp_tab_closed_while_context_alive, case_logout_sidecar_down_keeps_profile_message,
             case_default_logout_does_not_claim_profile_removed,
             case_cdp_clear_failure_is_not_no_cookie, case_stop_flag,
             case_bili_cookie_syncs_to_cli, case_cookie_names_reads_file]
    for case in cases:
        case()
    print(f"test_auth_flow: {len(cases)} cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())