"""P0 验收：设置、登录四态、插件评论能力。

跑法：python tests/test_settings.py
不联网、不弹 Chrome：登录走的是「cookie 文件在不在」的判断，评论用的是假宿主。
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 状态目录指到临时目录，别动真实的 cookie / settings。
_TMP_STATE = tempfile.mkdtemp(prefix="onefeed-state-")
os.environ["ONEFEED_HOME"] = _TMP_STATE


def _drop_tmp_state() -> None:
    """进程退出时删掉临时状态目录。

    sqlite 连接没显式关时文件还锁着，Windows 上第一轮 rmtree 会静默失败；
    gc 一次再重试几轮就够了。以前不删，仓库根堆了几十个 onefeed-state-* 空壳。
    """
    import gc
    import time

    gc.collect()
    for _ in range(4):
        shutil.rmtree(_TMP_STATE, ignore_errors=True)
        if not Path(_TMP_STATE).exists():
            return
        time.sleep(0.15)


atexit.register(_drop_tmp_state)

from fastapi.testclient import TestClient  # noqa: E402

from onefeed import settings as settings_mod  # noqa: E402
from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)


def expect_error(fn, label: str) -> None:
    global CHECKS
    try:
        fn()
    except ValueError:
        CHECKS += 1
        return
    raise AssertionError(label + "（应当报错但没有）")


class FakeHost:
    """只实现 comments 相关接口的假宿主。"""

    def __init__(self, plugins_dir: Path, supported: set[str], boom: bool = False):
        self.plugins_dir = Path(plugins_dir)
        self.supported = supported
        self.boom = boom
        self.calls = 0
        self.errors: list[str] = []

    def supports(self, plugin_id: str, feature: str) -> bool:
        return feature == "comments" and plugin_id in self.supported

    def comments(self, plugin_id: str, item, limit: int = 20, cursor: str | None = None):
        self.calls += 1
        if self.boom:
            raise RuntimeError(f"[{plugin_id}] 插件未实现 comments")
        if cursor:
            return {"items": [], "next": None}
        return {"items": [{"id": "c1", "author": "层主", "text": "第一条评论",
                           "like_count": 12, "created_at": int(time.time()) - 60}],
                "next": "2"}

    def discover(self):
        return []


def main() -> int:
    # ---------------------------------------------------------------- 设置校验
    check(set(settings_mod.DEFAULTS) >= {"plugins_dir", "registry_url", "per_plugin_limit",
                                         "comments_limit", "default_sort", "prune_days"},
          "默认设置项齐全")
    expect_error(lambda: settings_mod.validate({"nope": 1}), "未知键应当报错")
    expect_error(lambda: settings_mod.validate({"registry_url": "ftp://x"}), "registry 必须是 http(s)")
    expect_error(lambda: settings_mod.validate({"per_plugin_limit": 0}), "每轮条数下限")
    expect_error(lambda: settings_mod.validate({"per_plugin_limit": 51}), "每轮条数上限")
    expect_error(lambda: settings_mod.validate({"default_sort": "random"}), "排序只认两种")
    expect_error(lambda: settings_mod.validate({"plugins_dir": "Z:/not-a-dir"}), "插件目录必须存在")

    saved = settings_mod.save({"per_plugin_limit": 7, "comments_limit": 9,
                               "default_sort": "engagement"})
    check(saved["per_plugin_limit"] == 7, "保存后读回 7")
    check(settings_mod.load()["default_sort"] == "engagement", "保存后读回排序")
    check(settings_mod.settings_file().is_file(), "settings.json 落盘")
    # 环境变量优先于文件，但不写回
    os.environ["ONEFEED_REGISTRY"] = "https://example.com/registry.json"
    check(settings_mod.registry_url() == "https://example.com/registry.json", "env 覆盖 registry")
    settings_mod.save({"per_plugin_limit": 8})
    check("https://example.com/registry.json" not in settings_mod.settings_file().read_text(encoding="utf-8"),
          "env 覆盖的值不落盘")
    os.environ.pop("ONEFEED_REGISTRY")

    # ---------------------------------------------------------------- API
    tmp = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "settings-test.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    now = int(time.time())
    store.upsert_items([{
        "id": "bilibili:BV1", "platform": "bilibili", "kind": "video",
        "title": "一条用于评论测试的视频", "text": "", "author": "UP",
        "cover": "", "url": "https://example.com/v", "published_at": now,
        "like": 1, "comment": 1, "share": 0, "view": 10,
        "tags": [], "extra": {}, "fetched_at": now,
    }, {
        "id": "zhihu-hot:1", "platform": "zhihu-hot", "kind": "list",
        "title": "知乎热榜一条", "text": "", "author": "",
        "cover": "", "url": "https://example.com/z", "published_at": now,
        "like": 0, "comment": 0, "share": 0, "view": 0,
        "tags": [], "extra": {}, "fetched_at": now,
    }])
    app = create_app(store)
    client = TestClient(app)

    got = client.get("/api/settings")
    check(got.status_code == 200, "GET /api/settings 200")
    body = got.json()
    check(body["settings"]["per_plugin_limit"] == 8, "API 读到刚保存的值")
    check(body["resolved"]["registry_url"].startswith("https://"), "API 给出解析后的 registry")
    check(Path(body["resolved"]["state_dir"]) == Path(_TMP_STATE), "状态目录跟着 ONEFEED_HOME")

    put = client.put("/api/settings", json={"per_plugin_limit": 5})
    check(put.status_code == 200 and put.json()["settings"]["per_plugin_limit"] == 5, "PUT 生效")
    check(app.state.refresher.limit == 5, "PUT 直接把 runner.limit 改了")
    bad = client.put("/api/settings", json={"default_sort": "whatever"})
    check(bad.status_code == 400 and bad.json()["error"]["code"] == "bad_settings", "非法设置 400")

    # ---------------------------------------------------------------- 登录四态
    bili = client.get("/api/auth/bilibili").json()
    check(bili["state"] == "not_required" and bili["can_login"] is False, "B 站走 CLI，不开登录窗口")
    check("bili login" in bili["message"], "B 站提示里给出 CLI 命令")
    unknown = client.get("/api/auth/juejin").json()
    check(unknown["state"] == "not_required" and not unknown["can_login"], "其它插件不需要登录")
    xhs = client.get("/api/auth/xiaohongshu").json()
    check(xhs["state"] == "need_login" and xhs["can_login"] is True, "小红书未登录")
    check("登录窗口" in xhs["hint"], "提示告诉用户点登录窗口")

    rows = client.get("/api/auth").json()["rows"]
    ids = [r["plugin"] for r in rows]
    check({"xiaohongshu", "douyin", "zhihu", "bilibili"} <= set(ids), "登录行清单覆盖全部内置登录流程（含知乎）")
    check(all(r.get("can_login") or r.get("cli") for r in rows), "每个登录行都带 can_login/cli 标记")
    zhihu = client.get("/api/auth/zhihu").json()
    check(zhihu["state"] == "need_login" and zhihu["can_login"] is True, "知乎未登录且可开登录窗口")

    cookie_path = Path(_TMP_STATE) / "cookies" / "xiaohongshu.json"
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text('{"cookies":[{"name":"id_token","value":"x"}]}', encoding="utf-8")
    xhs2 = client.get("/api/auth/xiaohongshu").json()
    check(xhs2["state"] == "available", "放了 id_token 就是已登录")
    out = client.post("/api/auth/xiaohongshu/logout").json()
    check(out["ok"] and not cookie_path.exists(), "退出会删 cookie 文件")

    # ---------------------------------------------------------------- 评论
    app.state.refresher.host = FakeHost(Path(_TMP_STATE), {"bilibili"})
    ok = client.get("/api/item/bilibili:BV1/comments?limit=5").json()
    check(ok["supported"] is True and ok["items"][0]["author"] == "层主", "支持的插件返回评论")
    check(client.get("/api/item/zhihu-hot:1/comments").json()["supported"] is False,
          "没声明 comments 的插件返回 supported=false")
    hit = client.get("/api/item/bilibili:BV1/comments?limit=5").json()
    check(hit.get("from_cache") is True, "第二次走缓存")
    check(hit.get("next") == "2", "首页带下一页游标")
    tail = client.get("/api/item/bilibili:BV1/comments?limit=5&cursor=2").json()
    check(tail["items"] == [] and tail["next"] is None, "末页没有游标，前端据此提示去原站")

    app.state.refresher.host = FakeHost(Path(_TMP_STATE), {"bilibili"}, boom=True)
    # 缓存还在，先换一条 id 触发真正的调用
    store.upsert_items([{
        "id": "bilibili:BV2", "platform": "bilibili", "kind": "video",
        "title": "第二条", "text": "", "author": "UP", "cover": "",
        "url": "https://example.com/v2", "published_at": now, "like": 0,
        "comment": 0, "share": 0, "view": 0, "tags": [], "extra": {},
        "fetched_at": now,
    }])
    boom = client.get("/api/item/bilibili:BV2/comments").json()
    check(boom["supported"] is False, "插件未实现 comments 时降级成不支持")

    missing = client.get("/api/item/不存在/comments")
    check(missing.status_code == 404, "评论接口对未知条目 404")

    store.close()
    print(f"P0 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
