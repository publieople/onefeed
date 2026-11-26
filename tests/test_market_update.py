"""插件市场更新链路的验收（T40）：版本比较、更新保留开关、批量更新、自动更新设置。

跑法：uv run python tests/test_market_update.py
不联网：把 registry / 下载 / 文件列表换成假的，但走的是真实的 install →
sha256 校验 → 原子改名 → 写库 这条链路，所以它能抓到「更新把用户关掉的插件重新打开」这类 bug。
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

from onefeed import market  # noqa: E402
from onefeed import settings as settings_mod  # noqa: E402
from onefeed.market import _cache_dir  # noqa: E402
from onefeed.store import Store  # noqa: E402

CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)


def expect_raise(fn, label: str) -> None:
    global CHECKS
    try:
        fn()
    except Exception:
        CHECKS += 1
        return
    raise AssertionError(label + "（应当报错但没有）")


def write_plugin(root: Path, plugin_id: str, version: str) -> None:
    for name, blob in plugin_files(plugin_id, version).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(blob)


def plugin_files(plugin_id: str, version: str) -> dict[str, bytes]:
    return {
        "plugin.json": json.dumps({
            "schemaVersion": 1, "id": plugin_id, "name": plugin_id, "version": version,
            "minHostVersion": "0.2.0", "entry": "index.js",
            "capabilities": ["http"], "kinds": ["short"],
            "feeds": [{"id": "main", "name": "主源"}],
        }, ensure_ascii=False).encode("utf-8"),
        "index.js": ("module.exports={id:%r,version:%r,pull:async()=>({items:[]})};"
                     % (plugin_id, version)).encode("utf-8"),
    }


class Sandbox:
    """把 registry / 远端文件 / 插件目录全换成临时目录，其余走真实代码。"""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="onefeed-market-"))
        self.plugin_root = self.root / "plugins"
        self.plugin_root.mkdir(parents=True, exist_ok=True)
        self.remote: dict[str, dict[str, bytes]] = {}
        self.registry_entries: list[dict] = []
        self.fail_download: set[str] = set()

    def cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def add_remote(self, plugin_id: str, version: str) -> dict:
        files = plugin_files(plugin_id, version)
        self.remote[plugin_id] = files
        pkg = self.root / "pkg" / plugin_id
        if pkg.exists():
            import shutil
            shutil.rmtree(pkg)
        for name, blob in files.items():
            (pkg / name).parent.mkdir(parents=True, exist_ok=True)
            (pkg / name).write_bytes(blob)
        entry = {
            "id": plugin_id, "name": plugin_id, "version": version,
            "description": "测试插件", "author": "test", "kinds": ["short"],
            "capabilities": ["http"], "features": [], "feeds": ["main"],
            "sha256": market.dir_hash(pkg),
        }
        self.registry_entries = [e for e in self.registry_entries if e["id"] != plugin_id]
        self.registry_entries.append(entry)
        return entry


def patch_market(sb: Sandbox) -> list:
    saved = {
        "registry": market.registry,
        "remote": market._remote_files,
        "http": market._http_bytes,
        "plugins_root": market.plugins_root,
    }

    def fake_registry(force: bool = False) -> dict:
        return {"schemaVersion": 1, "plugins": sb.registry_entries, "from_cache": False}

    def fake_remote(plugin_id: str):
        if plugin_id in sb.fail_download:
            raise RuntimeError("下载失败（测试用）")
        files = sb.remote[plugin_id]
        return [(name, "fake://" + plugin_id + "/" + name) for name in files]

    def fake_http(url: str, timeout: float = 15.0) -> bytes:
        plugin_id, name = url[len("fake://"):].split("/", 1)
        return sb.remote[plugin_id][name]

    market.registry = fake_registry
    market._remote_files = fake_remote
    market._http_bytes = fake_http
    market.plugins_root = lambda: sb.plugin_root
    return saved


def restore_market(saved: dict) -> None:
    market.registry = saved["registry"]
    market._remote_files = saved["remote"]
    market._http_bytes = saved["http"]
    market.plugins_root = saved["plugins_root"]


def main() -> int:
    # ---------------------------------------------------------------- 版本比较
    check(market.version_key("0.2.1") == (0, 2, 1), "版本号拆成数字元组")
    check(market.version_key("") == (0,), "空版本当 0")
    check(market.cmp_version("0.1.0", "0.2.0") == -1, "0.1.0 < 0.2.0")
    check(market.cmp_version("0.2.0", "0.2.0") == 0, "同版本相等")
    check(market.cmp_version("1.0", "0.9.9") == 1, "1.0 > 0.9.9")
    check(market.cmp_version("0.2", "0.2.0") == 0, "缺失段补 0")

    # ---------------------------------------------------------------- 设置项
    check(settings_mod.DEFAULTS.get("auto_update") is False, "自动更新默认关")
    check(settings_mod.validate({"auto_update": True})["auto_update"] is True, "自动更新可开")
    for bad in ("yes", 1, None):
        expect_raise(lambda b=bad: settings_mod.validate({"auto_update": b}),
                     "自动更新只认 bool（给的是 " + repr(bad) + "）")
    saved_conf = settings_mod.save({"auto_update": True})
    check(saved_conf["auto_update"] is True, "自动更新写盘后读回 True")
    settings_mod.save({"auto_update": False})

    # ---------------------------------------------------------------- 存量插件：更新保留「已停用」
    sb = Sandbox()
    saved = patch_market(sb)
    store = Store(Path(_TMP_STATE) / "market-test.db")
    try:
        sb.add_remote("demo", "0.2.0")
        store.upsert_plugin("demo", "0.1.0", "old-sha", source="registry", enabled=0)

        entries = market.merged(store)["entries"]
        demo = next(e for e in entries if e["id"] == "demo")
        check(demo["update_available"] is True, "0.1.0 → 0.2.0 提示可更新")
        check(demo["latest_version"] == "0.2.0", "带出最新版本号")
        check(market.pending_updates(store) == [{"id": "demo", "from": "0.1.0", "to": "0.2.0"}],
              "pending_updates 只报可更新的")

        result = market.update(store, "demo")
        check(result["changed"] is True, "更新确实换了版本")
        check((result["from"], result["to"]) == ("0.1.0", "0.2.0"), "回带 from/to")
        row = next(p for p in store.list_plugins() if p["id"] == "demo")
        check(row["version"] == "0.2.0", "库里版本升到 0.2.0")
        check(bool(row["enabled"]) is False, "更新不会把用户关掉的插件重新打开")
        on_disk = json.loads((sb.plugin_root / "demo" / "plugin.json").read_text(encoding="utf-8"))
        check(on_disk["version"] == "0.2.0", "磁盘上的插件也换成新版")
        check(market.dir_hash(sb.plugin_root / "demo") ==
              next(e for e in sb.registry_entries if e["id"] == "demo")["sha256"],
              "落盘内容与 registry 的 sha256 一致")

        again = market.update(store, "demo")
        check(again["changed"] is False, "已是最新就不重装")
        expect_raise(lambda: market.update(store, "never-installed"), "没装的插件不能更新")

        # ------------------------------------------------ 缓存按版本分开：不会命旧包
        sb_cache = Sandbox()
        saved_cache = patch_market(sb_cache)
        store_cache = Store(Path(_TMP_STATE) / "market-cache.db")
        try:
            sb_cache.add_remote("gamma", "1.0.0")
            market.install(store_cache, "gamma")
            sb_cache.add_remote("gamma", "1.1.0")
            bumped = market.update(store_cache, "gamma")
            check(bumped["changed"] is True and bumped["to"] == "1.1.0",
                  "升过一次之后再升，不会命中上一版的旧缓存")
            on_disk = json.loads((sb_cache.plugin_root / "gamma" / "plugin.json")
                                 .read_text(encoding="utf-8"))
            check(on_disk["version"] == "1.1.0", "磁盘上是新版本而不是缓存里的旧包")
            caches = list((_cache_dir() / "plugins").glob("gamma-*"))
            check(len(caches) == 1, "旧版本缓存被清掉，只留当前 sha 那一份")
        finally:
            store_cache.close()
            restore_market(saved_cache)
            sb_cache.cleanup()

        # ---------------------------------------- 没有 sha256 时不复用缓存：换了包也得重新下
        sb_nohash = Sandbox()
        saved_nohash = patch_market(sb_nohash)
        store_nohash = Store(Path(_TMP_STATE) / "market-nohash.db")
        try:
            entry = sb_nohash.add_remote("nohash", "1.0.0")
            entry.pop("sha256", None)
            market.install(store_nohash, "nohash")
            check(json.loads((sb_nohash.plugin_root / "nohash" / "plugin.json")
                             .read_text(encoding="utf-8"))["version"] == "1.0.0",
                  "无 sha：第一版装好")
            entry = sb_nohash.add_remote("nohash", "1.1.0")
            entry.pop("sha256", None)
            bumped = market.update(store_nohash, "nohash")
            check(bumped["changed"] is True and bumped["to"] == "1.1.0",
                  "无 sha：registry 升版后仍能更新")
            on_disk = json.loads((sb_nohash.plugin_root / "nohash" / "plugin.json")
                                 .read_text(encoding="utf-8"))
            check(on_disk["version"] == "1.1.0", "无 sha：装的是新包而不是缓存里的旧包")
            check(not list((_cache_dir() / "plugins").glob("nohash-*")),
                  "无 sha：不写也清掉 nohash 缓存")
        finally:
            store_nohash.close()
            restore_market(saved_nohash)
            sb_nohash.cleanup()
        # ------------------------------------ 远端文件名/插件 id 不能带路径穿越
        sb_path = Sandbox()
        saved_path = patch_market(sb_path)
        store_path = Store(Path(_TMP_STATE) / "market-path.db")
        try:
            entry = sb_path.add_remote("evil", "1.0.0")
            entry.pop("sha256", None)
            sb_path.remote["evil"]["../../escape.txt"] = b"escape"
            expect_raise(lambda: market.install(store_path, "evil"),
                         "包内 ../ 路径应当拒绝安装")
            check(not (sb_path.root / "escape.txt").exists(), "包内 ../ 没把文件写到包外")

            sb_path.registry_entries.append({
                "id": "../id-escape", "name": "evil", "version": "1.0.0",
                "description": "", "author": "", "kinds": [], "capabilities": [],
                "features": [], "feeds": [], "sha256": "",
            })
            expect_raise(lambda: market.install(store_path, "../id-escape"),
                         "插件 id 带 ../ 应当拒绝安装")
            check(not (sb_path.root / "id-escape").exists(), "插件 id 没把目录建到 plugins 外")
        finally:
            store_path.close()
            restore_market(saved_path)
            sb_path.cleanup()

        # ------------------------------------------------------- 批量更新：一个失败不影响另一个
        sb.add_remote("alpha", "1.1.0")
        sb.add_remote("beta", "2.0.0")
        store.upsert_plugin("alpha", "1.0.0", "sha-a", source="registry", enabled=1)
        store.upsert_plugin("beta", "1.0.0", "sha-b", source="registry", enabled=1)
        sb.fail_download.add("beta")
        batch = market.update_all(store)
        check(batch["pending"] == 2, "两个可更新")
        check([u["id"] for u in batch["updated"]] == ["alpha"], "alpha 更新成功")
        check([f["id"] for f in batch["failed"]] == ["beta"], "beta 失败被记录")
        check(batch["ok"] is False, "有失败时 ok=False")
        sb.fail_download.clear()
        batch2 = market.update_all(store)
        check([u["id"] for u in batch2["updated"]] == ["beta"],
          "修好以后 beta 补上了；实际 " + json.dumps(batch2, ensure_ascii=False))
        check(batch2["failed"] == [] and batch2["ok"] is True, "补更不再报失败")
        batch3 = market.update_all(store)
        check(batch3["pending"] == 0 and batch3["updated"] == [], "全绿之后什么都不做")
    finally:
        store.close()
        restore_market(saved)
        sb.cleanup()

    # ---------------------------------------------------------------- 原子安装：失败回滚
    # 真实事故：旧安装器先 rmtree(target) 再 rename，rename 被占用就只剩空目录。
    # 下面把每一步单独打坏，确认旧插件和旧库记录都还在。
    sb_atomic = Sandbox()
    saved_atomic = patch_market(sb_atomic)
    store_atomic = Store(Path(_TMP_STATE) / "market-atomic.db")
    try:
        sb_atomic.add_remote("delta", "1.0.0")
        market.install(store_atomic, "delta")
        old_manifest = (sb_atomic.plugin_root / "delta" / "plugin.json").read_text(encoding="utf-8")
        check(json.loads(old_manifest)["version"] == "1.0.0", "原子安装：旧版本先装好")
        check(list(sb_atomic.root.glob(".of-*")) == [], "原子安装：成功后台临时目录已清理")

        # 1) 换入那一次 rename 失败：旧目录必须回来
        sb_atomic.add_remote("delta", "1.1.0")
        original_move = market._move_path
        calls = {"n": 0}

        def flaky_move(src, dst):
            if Path(dst) == sb_atomic.plugin_root / "delta" and calls["n"] == 0:
                calls["n"] += 1
                raise OSError("模拟目录被占用")
            return original_move(src, dst)

        market._move_path = flaky_move
        try:
            expect_raise(lambda: market.update(store_atomic, "delta"),
                         "rename 失败时更新应当报错")
        finally:
            market._move_path = original_move
        check((sb_atomic.plugin_root / "delta" / "plugin.json").read_text(encoding="utf-8") == old_manifest,
              "原子安装：rename 失败后旧目录原样回来")
        row = next(p for p in store_atomic.list_plugins() if p["id"] == "delta")
        check(row["version"] == "1.0.0", "原子安装：rename 失败后库记录不动")
        check(list(sb_atomic.root.glob(".of-*")) == [], "原子安装：回滚成功后临时目录已清理")

        # 2) 换入成功但写库失败：目录与库都要回到旧版本
        sb_atomic.add_remote("delta", "1.1.0")
        original_upsert = store_atomic.upsert_plugin

        def broken_upsert(*args, **kwargs):
            raise RuntimeError("模拟数据库写入失败")

        store_atomic.upsert_plugin = broken_upsert
        try:
            expect_raise(lambda: market.install(store_atomic, "delta"),
                         "写库失败时安装应当报错")
        finally:
            store_atomic.upsert_plugin = original_upsert
        check((sb_atomic.plugin_root / "delta" / "plugin.json").read_text(encoding="utf-8") == old_manifest,
              "原子安装：写库失败后旧目录原样回来")
        row = next(p for p in store_atomic.list_plugins() if p["id"] == "delta")
        check(row["version"] == "1.0.0", "原子安装：写库失败后库记录还是旧的")
        check(list(sb_atomic.root.glob(".of-*")) == [], "原子安装：写库失败回滚后临时目录已清理")

        # 3) 缓存复制失败不该拖垮安装：新版本照常落盘、写库，只带警告
        sb_atomic.add_remote("delta", "1.2.0")
        original_cache = market._refresh_cache

        def broken_cache(*args, **kwargs):
            raise OSError("模拟缓存目录只读")

        market._refresh_cache = broken_cache
        try:
            result = market.install(store_atomic, "delta")
        finally:
            market._refresh_cache = original_cache
        check(result["version"] == "1.2.0", "缓存失败：插件仍然装成新版本")
        check(bool(result.get("cache_warning")), "缓存失败：结果里带警告而不是静默")
        row = next(p for p in store_atomic.list_plugins() if p["id"] == "delta")
        check(row["version"] == "1.2.0", "缓存失败：库记录也升到新版本")
        on_disk = json.loads((sb_atomic.plugin_root / "delta" / "plugin.json").read_text(encoding="utf-8"))
        check(on_disk["version"] == "1.2.0", "缓存失败：磁盘上是新版本")

        # 4) 卸载时删库失败：目录要移回去，不能出现「目录没了、库还在」
        original_delete = store_atomic.delete_plugin

        def broken_delete(_plugin_id):
            raise RuntimeError("模拟删库失败")

        store_atomic.delete_plugin = broken_delete
        try:
            expect_raise(lambda: market.uninstall(store_atomic, "delta"),
                         "删库失败时卸载应当报错")
        finally:
            store_atomic.delete_plugin = original_delete
        check((sb_atomic.plugin_root / "delta" / "plugin.json").exists(),
              "原子卸载：删库失败后目录移回来了")
        check(any(p["id"] == "delta" for p in store_atomic.list_plugins()),
              "原子卸载：删库失败后库记录还在")
    finally:
        store_atomic.close()
        restore_market(saved_atomic)
        sb_atomic.cleanup()

    # ---------------------------------------------------------------- 进程崩溃后的恢复
    # 换目录时进程被强杀，旧目录在隐藏工作目录的 previous 里；启动时不能当没发生。
    sb_recover = Sandbox()
    saved_recover = patch_market(sb_recover)
    store_recover = Store(Path(_TMP_STATE) / "market-recover.db")
    try:
        # 1) 旧目录已移走、新目录还没换入：备份移回去，库补登记
        target = sb_recover.plugin_root / "eta"
        work = sb_recover.root / ".of-eta-crash"
        backup = work / "previous"
        backup.mkdir(parents=True)
        write_plugin(backup, "eta", "1.0.0")
        (work / "meta.json").write_text(json.dumps({
            "plugin_id": "eta", "target": str(target), "action": "install",
        }), encoding="utf-8")
        check(not target.exists(), "崩溃恢复：换入前 target 确实不在")
        recovered = market.recover_installs(store_recover, sb_recover.plugin_root)
        check(recovered == 1, "崩溃恢复：恢复了一个备份")
        check((target / "plugin.json").exists(), "崩溃恢复：旧目录移回 target")
        on_disk = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        check(on_disk["version"] == "1.0.0", "崩溃恢复：恢复的是旧版本")
        check(not work.exists(), "崩溃恢复：恢复后工作目录清理掉")
        row = next(p for p in store_recover.list_plugins() if p["id"] == "eta")
        check(row["version"] == "1.0.0", "崩溃恢复：库也补登记了")

        # 2) 新目录已换入、库还停在旧版本：按磁盘 manifest 补库
        target2 = sb_recover.plugin_root / "theta"
        write_plugin(target2, "theta", "1.1.0")
        work2 = sb_recover.root / ".of-theta-crash"
        backup2 = work2 / "previous"
        backup2.mkdir(parents=True)
        write_plugin(backup2, "theta", "1.0.0")
        (work2 / "meta.json").write_text(json.dumps({
            "plugin_id": "theta", "target": str(target2), "action": "install",
        }), encoding="utf-8")
        store_recover.upsert_plugin("theta", "1.0.0", "old-sha", source="registry", enabled=0)
        market.recover_installs(store_recover, sb_recover.plugin_root)
        row2 = next(p for p in store_recover.list_plugins() if p["id"] == "theta")
        check(row2["version"] == "1.1.0", "崩溃恢复：新目录已换入时库补齐到新版本")
        check(bool(row2["enabled"]) is False, "崩溃恢复：补齐版本不擅自打开已停用插件")
        check(not work2.exists(), "崩溃恢复：补库后工作目录清理掉")

        # 3) 卸载后、删备份前崩溃：库记录已删，备份可以直接清
        target3 = sb_recover.plugin_root / "iota"
        work3 = sb_recover.root / ".of-iota-crash"
        backup3 = work3 / "previous"
        backup3.mkdir(parents=True)
        write_plugin(backup3, "iota", "1.0.0")
        (work3 / "meta.json").write_text(json.dumps({
            "plugin_id": "iota", "target": str(target3), "action": "uninstall",
        }), encoding="utf-8")
        market.recover_installs(store_recover, sb_recover.plugin_root)
        check(not target3.exists(), "崩溃恢复：卸载已写库时不再把目录恢复回来")
        check(not work3.exists(), "崩溃恢复：卸载完成后的备份被清掉")
    finally:
        store_recover.close()
        restore_market(saved_recover)
        sb_recover.cleanup()

    # ---------------------------------------------------------------- 接口层
    from fastapi.testclient import TestClient
    from onefeed.app import create_app

    sb2 = Sandbox()
    saved2 = patch_market(sb2)
    store2 = Store(Path(_TMP_STATE) / "market-api.db")
    try:
        sb2.add_remote("gamma", "0.3.0")
        store2.upsert_plugin("gamma", "0.2.0", "sha-g", source="registry", enabled=1)
        app = create_app(store=store2, plugins_dir=sb2.plugin_root)
        client = TestClient(app)

        updates = client.get("/api/market/updates")
        check(updates.status_code == 200, "GET /api/market/updates 200")
        check(updates.json()["count"] == 1, "报到 1 个可更新")

        dup = client.post("/api/plugins/gamma/update")
        check(dup.status_code == 200, "POST /api/plugins/gamma/update 200")
        check(dup.json()["result"]["to"] == "0.3.0", "接口回带目标版本")

        empty = client.post("/api/plugins/gamma/update")
        check(empty.json()["result"]["changed"] is False, "再点一次就是「已是最新」")

        bad = client.post("/api/plugins/nope/update")
        check(bad.status_code == 400, "没装的插件更新返回 400")
        body = bad.json()
        check((body.get("detail") or body.get("error") or {}).get("code") == "update_failed",
              "错误码是 update_failed（实际：" + json.dumps(body, ensure_ascii=False)[:120] + "）")

        allresp = client.post("/api/market/update-all")
        check(allresp.status_code == 200, "POST /api/market/update-all 200")
        check(allresp.json()["result"]["pending"] == 0, "已经没有待更新的了")

        plugins = client.get("/api/plugins").json()
        gamma = next(e for e in plugins["market"]["entries"] if e["id"] == "gamma")
        check(gamma["update_available"] is False, "更新后不再提示可更新")
        check(gamma["installed_version"] == "0.3.0", "市场页读到的新版本")

        # ------------------------------------------------ 目录被手工删掉：刷新目录要清幽灵记录
        # 真实事故：bilibili 目录被删，库里的行还在，市场页继续显示「已安装」，
        # 卸载接口又因为目录不存在而拒绝，结果既卸不掉也装不回来。
        sb2.add_remote("ghost", "1.0.0")
        store2.upsert_plugin("ghost", "1.0.0", "ghost-sha", source="registry", enabled=1)
        check(not (sb2.plugin_root / "ghost").exists(), "ghost 目录一开始就不在")
        refreshed = client.get("/api/plugins?refresh_market=true").json()
        check(not any(p["id"] == "ghost" for p in refreshed["installed"]),
              "刷新目录后幽灵记录被清掉")
        ghost_market = next(e for e in refreshed["market"]["entries"] if e["id"] == "ghost")
        check(ghost_market["installed"] is False, "市场页重新出现「安装」")

        installed = client.post("/api/plugins/ghost/install")
        check(installed.status_code == 200, "幽灵记录清掉后可以重新安装")
        check((sb2.plugin_root / "ghost" / "plugin.json").exists(), "重装后目录回来了")
        after = client.get("/api/plugins").json()
        check(any(p["id"] == "ghost" for p in after["installed"]), "重装后库里也登记了")

        # 目录再被删掉：卸载不能报「没有安装」，要幂等地清掉库记录
        shutil.rmtree(sb2.plugin_root / "ghost")
        removed = client.delete("/api/plugins/ghost")
        check(removed.status_code == 200, "目录不在时卸载仍返回 200")
        check(removed.json()["result"]["removed"] is False, "卸载结果标明没有实际删目录")
        final = client.get("/api/plugins").json()
        check(not any(p["id"] == "ghost" for p in final["installed"]),
              "目录不在时卸载也清掉了库记录")
    finally:
        store2.close()
        restore_market(saved2)
        sb2.cleanup()

    print(f"market_update ok（{CHECKS} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())