"""刷新链路 + 平台冷却的守门。

对应真机上翻过的车：
- 演示模式每轮重放同一批样例，点刷新「看起来成功了但内容没变」；
- 首屏条目的时间键把没发布时间的条目算成一天前，刚抓到的永远排在后面；
- 平台被连续触发，风控直接给空列表，看起来像「这个平台今天没内容」。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ONEFEED_HOME", tempfile.mkdtemp(prefix="onefeed-refresh-"))

from onefeed import settings as settings_mod  # noqa: E402
from onefeed.service import RefreshRunner  # noqa: E402
from onefeed.store import FRESH_KEY, Store  # noqa: E402
from plugin_runtime.host import PluginHost  # noqa: E402


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def make_store() -> Store:
    return Store(Path(tempfile.mkdtemp(prefix="onefeed-refresh-db-")) / "test.db")


def wait_idle(runner: RefreshRunner, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while runner.running() and time.time() < deadline:
        time.sleep(0.02)
    assert not runner.running(), "后台线程没有按时收尾"


def test_intervals_merge_defaults_and_clamp():
    defaults = dict(settings_mod.DEFAULT_INTERVALS)
    assert settings_mod.platform_intervals({}) == defaults
    assert defaults["v2ex"] > 0 and defaults["zhihu-hot"] > 0, "每个平台都要有默认频率"

    merged = settings_mod.platform_intervals(
        {"v2ex": 0, "bilibili": 60, "junk": "abc", "huge": 10 ** 9}
    )
    assert merged["v2ex"] == 0, "0 = 不限，要能显式关掉"
    assert merged["bilibili"] == 60, "覆盖值要盖过默认"
    assert "junk" not in merged, "读不出来的值直接丢，别把脏数据写进冷却表"
    assert merged["huge"] == settings_mod.MAX_INTERVAL, "上限要夹住，别让一个手误把平台封一天以上"


def test_validate_rejects_bad_intervals():
    for patch, needle in (
        ({"platform_intervals": []}, "对象"),
        ({"platform_intervals": {"v2ex": "abc"}}, "整数秒"),
        ({"platform_intervals": {"v2ex": -1}}, "0–"),
        ({"platform_intervals": {"v2ex": settings_mod.MAX_INTERVAL + 1}}, "0–"),
    ):
        try:
            settings_mod.validate(patch)
        except ValueError as exc:
            assert needle in str(exc), f"错误文案要能直接给人看：{exc}"
        else:  # pragma: no cover
            raise AssertionError(f"{patch} 应该被拒绝")


def test_fresh_key_does_not_age_items_without_publish_time():
    # 抓取时间和发布时间一样新时，条目必须还在首屏；以前减 86400 会把它压到一天前。
    assert "i.fetched_at" in FRESH_KEY
    assert "- 86400" not in FRESH_KEY


def test_demo_replays_do_not_consume_the_platform_budget():
    store = make_store()
    run = store.start_run("v2ex", demo=True)
    store.finish_run(run, True, 5)
    assert store.last_pull_at("v2ex") == 0, "演示重放不是真的调平台，不该触发冷却"

    real = store.start_run("v2ex")
    store.finish_run(real, True, 3)
    assert store.last_pull_at("v2ex") > 0


def test_last_pull_at_counts_attempts_not_successes():
    store = make_store()
    assert store.last_pull_at("v2ex") == 0

    run_id = store.start_run("v2ex")
    store.finish_run(run_id, False, 0, "boom")
    failed = store.last_pull_at("v2ex")
    assert failed > 0, "失败也是一次调用，冷却必须算它"

    time.sleep(0.01)
    ok_id = store.start_run("v2ex")
    store.finish_run(ok_id, True, 3)
    assert store.last_pull_at("v2ex") >= failed
    assert store.last_pull_at("juejin") == 0, "冷却按平台算，不许串台"


def test_trigger_skips_a_platform_that_just_ran():
    store = make_store()
    run_id = store.start_run("v2ex")
    store.finish_run(run_id, True, 3)

    runner = RefreshRunner(store)
    started, state = runner.trigger(platforms=["v2ex"])
    assert started is True
    assert state["running"] is False, "全被拦时不该起线程"
    assert "冷却" in state["error"]
    entry = state["plugins"]["v2ex"]
    assert entry["status"] == "skipped"
    assert entry["next_at"] > time.time()
    assert "还要等" in entry["note"]
    assert state["done"] == state["total"] == 1


def test_trigger_survives_a_missing_plugin_dir():
    # CI 里没有仓库内的 plugins/：触发采集不能因为「发现插件失败」整段 500。
    # 显式点名平台时，冷却仍要照常算，错误记在 host.errors 里交给插件页。
    store = make_store()
    run_id = store.start_run("v2ex")
    store.finish_run(run_id, True, 3)

    missing = Path(tempfile.mkdtemp(prefix="onefeed-no-plugins-")) / "plugins"
    runner = RefreshRunner(store, host=PluginHost(plugins_dir=missing))
    started, state = runner.trigger(platforms=["v2ex"])
    assert started is True
    assert state["running"] is False
    assert state["plugins"]["v2ex"]["status"] == "skipped"
    assert state["done"] == state["total"] == 1
    assert any("插件目录不存在" in e for e in runner.host.errors)


def test_refresh_api_explains_a_missing_plugin_dir():
    from fastapi.testclient import TestClient

    from onefeed.app import create_app

    store = make_store()
    missing = Path(tempfile.mkdtemp(prefix="onefeed-no-plugins-api-")) / "plugins"
    client = TestClient(create_app(store=store, plugins_dir=missing))
    resp = client.post("/api/refresh", json={})
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "refresh_unavailable", "目录缺失不能伪装成「已经在刷新」"
    assert "插件目录不存在" in error["message"]


def test_trigger_batches_by_platform_and_force_bypasses_cooldown():
    store = make_store()
    run_id = store.start_run("v2ex")
    store.finish_run(run_id, True, 3)

    runner = RefreshRunner(store)
    runner._load = lambda pid: []  # 不联网：只验证排队与放行
    started, state = runner.trigger(platforms=["v2ex", "juejin"])
    assert started is True
    assert state["plugins"]["v2ex"]["status"] == "skipped", "抓过的平台被拦"
    assert state["plugins"]["juejin"]["status"] in ("queued", "running", "ok"), "没抓过的照抓"
    wait_idle(runner)
    final = runner.snapshot()
    assert final["plugins"]["v2ex"]["status"] == "skipped"
    assert final["plugins"]["juejin"]["status"] == "ok"

    # force：用户明确点「仍要抓」时越过冷却
    runner._load = lambda pid: []
    started, forced = runner.trigger(platforms=["v2ex"], force=True)
    assert started is True and forced["plugins"]["v2ex"]["status"] == "queued"
    wait_idle(runner)
    assert runner.snapshot()["plugins"]["v2ex"]["status"] == "ok"


def test_cancel_stops_queued_platforms():
    """叫停采集：正在跑的平台让它跑完，还没开始的立刻标成 cancelled。

    真机上的停止按钮走的就是这条路——Agent 的 run 取消后必须把 RefreshRunner
    一起停下，否则界面说「停下了」、后台还在一个个抓。
    """
    store = make_store()
    runner = RefreshRunner(store)

    def slow(_pid: str):
        time.sleep(0.25)
        return []

    runner._load = slow
    started, state = runner.trigger(
        platforms=["v2ex", "juejin", "zhihu"], force=True,
        source="agent", owner="run-cancel")
    assert started is True
    assert state["source"] == "agent" and state["owner"] == "run-cancel"

    deadline = time.time() + 2
    while runner.snapshot()["plugins"]["v2ex"]["status"] != "running" and time.time() < deadline:
        time.sleep(0.01)
    assert runner.snapshot()["plugins"]["v2ex"]["status"] == "running"

    assert runner.cancel(owner="someone-else") is False, "别人的轮次不能被顺手停掉"
    assert runner.cancel(owner="run-cancel") is True
    wait_idle(runner, 3.0)

    final = runner.snapshot()
    assert final["phase"] == "cancelled"
    assert final["cancel_requested"] is True
    assert final["plugins"]["v2ex"]["status"] == "ok", "正在跑的那个允许跑完"
    assert final["plugins"]["juejin"]["status"] == "cancelled"
    assert final["plugins"]["zhihu"]["status"] == "cancelled"
    assert final["cancelled"] == 2, "剩下几个平台都要记进 cancelled，进度条不能停在 1/3"
    assert final["done"] == final["total"] == 3



def test_auto_source_is_kept_and_unknown_falls_back_to_user():
    """滚到底的自动检查要靠 source=auto 才能不演刷新；手点的那轮仍是 user。"""
    runner = RefreshRunner(make_store())
    runner._load = lambda _pid: []
    started, state = runner.trigger(platforms=["v2ex"], force=True, source="auto")
    assert started is True
    assert state["source"] == "auto", "自动检查的来源被吞了，前端会当成手点刷新"
    wait_idle(runner)
    started, state = runner.trigger(platforms=["juejin"], force=True, source="who-knows")
    assert started is True
    assert state["source"] == "user", "未知来源不能漏进状态，前端的分支只认三类"


def test_demo_mode_is_skipped_not_failed_and_cooldown_ignored():
    store = make_store()
    runner = RefreshRunner(store)
    runner._load = lambda pid: [] if pid != "zhihu" else _raise_fixture_missing()
    os.environ["ONEFEED_DEMO"] = "1"
    try:
        run = store.start_run("v2ex")
        store.finish_run(run, True, 1)
        started, state = runner.trigger(platforms=["v2ex", "zhihu"])
        assert started is True and state["plugins"]["v2ex"]["status"] == "queued", \
            "演示模式不联网，冷却没有意义"
        wait_idle(runner)
        final = runner.snapshot()
        assert final["plugins"]["v2ex"]["status"] == "ok"
        assert final["plugins"]["zhihu"]["status"] == "skipped", "缺样例算跳过，不算失败"
        assert "演示模式没有" in final["plugins"]["zhihu"]["note"]
    finally:
        os.environ.pop("ONEFEED_DEMO", None)


def _raise_fixture_missing():
    from onefeed.service import FixtureMissing

    raise FixtureMissing("演示模式没有 zhihu.json 的样例（在线跑一次 --warmup 就能补上）")


def test_new_count_counts_items_that_appear_for_the_first_time():
    """插件交回来的是 Item 对象，不是 dict：按 dict 过滤会让新增数永远是 0。

    真机翻过车：一轮抓了 78 条、库从 1155 长到 1220，状态条却说「+0 条」——
    因为 isinstance(it, dict) 把所有条目都筛掉了，known 空、fresh 也就恒为 0。
    """
    from plugin_runtime.host import to_item

    store = make_store()
    runner = RefreshRunner(store)
    batch = [
        to_item("v2ex", {"native_id": f"topic:{i}", "title": t,
                         "url": f"https://v2ex.com/t/{i}", "kind": "text"},
                fetched_at=int(time.time()))
        for i, t in enumerate(["一", "二", "三"])
    ]
    runner._load = lambda pid: list(batch)

    started, _ = runner.trigger(platforms=["v2ex"], force=True)
    assert started is True
    wait_idle(runner)
    first = runner.snapshot()
    assert first["plugins"]["v2ex"]["new_count"] == 3, "第一次见到这三条，就是 3 条新增"
    assert first["new_total"] == 3

    runner._load = lambda pid: list(batch)
    runner.trigger(platforms=["v2ex"], force=True)
    wait_idle(runner)
    again = runner.snapshot()
    assert again["plugins"]["v2ex"]["new_count"] == 0, "同样的三条再来一轮不该算新增"
    assert again["new_total"] == 0


def test_frontend_says_when_nothing_can_change():
    shell = read("web/src/layout/Shell.tsx")
    assert "离线演示模式" in shell and "health?.demo" in shell, "演示模式要摆在脸上"
    app = read("web/src/App.tsx")
    assert "这一轮只是重放" in app, "刷新完成时要说明为什么没新内容"
    assert "仍要抓" in app and "force" in app, "冷却拦住时要给一条明确的出路"
    assert "新增" in app and "平台冷却中" in app
    topbar = read("web/src/components/TopBar.tsx")
    assert "onClick={clickRefresh}" in topbar, "别把点击事件当 force 传下去"
    # 进度件就贴在刷新按钮左边：运行中点它不必把人送到别处，重新亮一下就够
    assert "RefreshProgress" in topbar, "运行中点刷新要有落点"
    assert "setHint((n) => n + 1);" in topbar, "再点一下要把进度件重新亮出来"
    assert 'data-refresh-bar="1"' in read("web/src/components/RefreshProgress.tsx"), "落点得是那件真进度"
    assert "force === true" in app, "只认严格 true，SyntheticEvent 不能被 stringify"
    page = read("web/src/pages/SettingsPage.tsx")
    assert "平台抓取间隔" in page and "intervalPlatforms.map" in page
    assert "platformList(installed.map" in page, "间隔输入要跟着已装插件走，不能写死平台表"
    api = read("onefeed/api.py")
    assert '"intervals"' in api, "前端要知道当前生效值，不能只看空的覆盖表"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all refresh tests passed")
