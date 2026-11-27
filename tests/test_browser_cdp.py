"""专用 Chrome sidecar 的配置与启动参数（不真的连浏览器）。"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plugin_runtime import browser_cdp, capabilities  # noqa: E402


def case_endpoint_and_enabled():
    old = os.environ.pop("ONEFEED_BROWSER_CDP", None)
    try:
        assert browser_cdp.endpoint() is None
        assert browser_cdp.enabled() is False
        os.environ["ONEFEED_BROWSER_CDP"] = "  http://127.0.0.1:9333/  "
        assert browser_cdp.endpoint() == "http://127.0.0.1:9333"
        assert browser_cdp.enabled() is True
    finally:
        if old is None:
            os.environ.pop("ONEFEED_BROWSER_CDP", None)
        else:
            os.environ["ONEFEED_BROWSER_CDP"] = old
    print("case_endpoint_and_enabled ok")


def case_profile_dir():
    old = os.environ.pop("ONEFEED_BROWSER_PROFILE", None)
    try:
        assert browser_cdp.profile_dir().name == "chrome-profile"
        os.environ["ONEFEED_BROWSER_PROFILE"] = "/tmp/onefeed-sidecar"
        assert browser_cdp.profile_dir() == Path("/tmp/onefeed-sidecar")
    finally:
        if old is None:
            os.environ.pop("ONEFEED_BROWSER_PROFILE", None)
        else:
            os.environ["ONEFEED_BROWSER_PROFILE"] = old
    print("case_profile_dir ok")


def case_win_path():
    if os.name == "nt":
        assert browser_cdp._win_path(r"C:\temp\x") == r"C:\temp\x"
    else:
        assert browser_cdp._win_path("/mnt/c/Program Files/Chrome/chrome.exe") == (
            r"C:\Program Files\Chrome\chrome.exe")
    print("case_win_path ok")


def case_launch_args_include_proxy():
    old_proxy = os.environ.get("ONEFEED_BROWSER_PROXY")
    profile = Path(tempfile.mkdtemp(prefix="onefeed-cdp-test-"))
    captured = {}
    os.environ["ONEFEED_BROWSER_PROXY"] = "http://127.0.0.1:7890"

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return object()

    try:
        with mock.patch.object(browser_cdp, "find_chrome", return_value="/fake/chrome"), \
                mock.patch.object(browser_cdp, "profile_dir", return_value=profile), \
                mock.patch.object(browser_cdp.subprocess, "Popen", side_effect=fake_popen):
            browser_cdp._launch("http://127.0.0.1:9223")
    finally:
        if old_proxy is None:
            os.environ.pop("ONEFEED_BROWSER_PROXY", None)
        else:
            os.environ["ONEFEED_BROWSER_PROXY"] = old_proxy
        for child in profile.iterdir():
            child.unlink()
        profile.rmdir()

    args = captured["args"]
    assert "--remote-debugging-port=9223" in args
    assert "--remote-debugging-address=127.0.0.1" in args
    assert "--remote-allow-origins=*" not in args
    assert any(a.startswith("--user-data-dir=") for a in args)
    assert "--proxy-server=http://127.0.0.1:7890" in args
    assert args[-1] == "about:blank"
    if os.name == "nt":
        # Windows 用 creationflags 脱离父进程，不能同时传 POSIX 的 start_new_session。
        flags = captured["kwargs"].get("creationflags")
        assert flags is not None
        assert flags & getattr(subprocess, "DETACHED_PROCESS", 0)
        assert "start_new_session" not in captured["kwargs"]
    else:
        assert captured["kwargs"].get("start_new_session") is True
    print("case_launch_args_include_proxy ok")


def case_domain_matches_site_and_subdomains():
    assert browser_cdp._domain_matches(".zhihu.com", ".zhihu.com")
    assert browser_cdp._domain_matches("www.zhihu.com", ".zhihu.com")
    assert browser_cdp._domain_matches("zhihu.com", "zhihu.com")
    assert not browser_cdp._domain_matches("notzhihu.com", ".zhihu.com")
    assert not browser_cdp._domain_matches("zhihu.com.evil.test", ".zhihu.com")
    print("case_domain_matches_site_and_subdomains ok")


def case_clear_cookies_does_not_launch():
    old = os.environ.get("ONEFEED_BROWSER_CDP")
    os.environ["ONEFEED_BROWSER_CDP"] = "http://127.0.0.1:9223"
    try:
        with mock.patch.object(browser_cdp, "_alive", return_value=False), \
                mock.patch.object(browser_cdp, "_launch") as launch:
            assert browser_cdp.clear_cookies() is False
            launch.assert_not_called()
    finally:
        if old is None:
            os.environ.pop("ONEFEED_BROWSER_CDP", None)
        else:
            os.environ["ONEFEED_BROWSER_CDP"] = old
    print("case_clear_cookies_does_not_launch ok")


def case_clean_env_keeps_runtime_config():
    keys = ["ONEFEED_HOME", "ONEFEED_BROWSER_CDP", "ONEFEED_BROWSER_PROFILE",
            "ONEFEED_CHROME_EXE", "ONEFEED_BROWSER_PROXY"]
    old = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = "test-" + key.lower()
        env = capabilities.clean_env()
        for key in keys:
            assert env.get(key) == "test-" + key.lower(), key
        assert env.get("PYTHONIOENCODING") == "utf-8"
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("case_clean_env_keeps_runtime_config ok")


def main() -> int:
    cases = [case_endpoint_and_enabled, case_profile_dir, case_win_path,
             case_launch_args_include_proxy, case_domain_matches_site_and_subdomains,
             case_clear_cookies_does_not_launch, case_clean_env_keeps_runtime_config]
    for case in cases:
        case()
    print(f"test_browser_cdp: {len(cases)} cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
