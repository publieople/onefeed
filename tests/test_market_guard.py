"""OF-36 验收：registry 必须 https、条目必须带 sha256、包内清单 id 必须一致。

跑法：
    python tests/test_market_guard.py

不联网：registry / 远端文件 / 下载都换成假的，install 走真实的「下载 → sha256
校验 → 原子换入 → 写库」链路。
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP_STATE = tempfile.mkdtemp(prefix="of-market-guard-")
os.environ["ONEFEED_HOME"] = _TMP_STATE


def _drop_tmp_state() -> None:
    import gc

    gc.collect()
    for _ in range(4):
        shutil.rmtree(_TMP_STATE, ignore_errors=True)
        if not Path(_TMP_STATE).exists():
            return
        import time

        time.sleep(0.15)


atexit.register(_drop_tmp_state)

from onefeed import market  # noqa: E402
from onefeed.store import Store  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def expect_raise(fn, label: str, contains: str = "") -> str:
    global CHECKS
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - 就是要任何失败
        CHECKS += 1
        text = f"{type(exc).__name__}: {exc}"
        if contains and contains not in text:
            raise AssertionError(f"{label}（报错信息里没有 {contains!r}：{text}）")
        if VERBOSE:
            print(f"  ok  {label}")
        return text
    raise AssertionError(label + "（应当报错但没有）")


# ---------------------------------------------------------------- 假市场

def plugin_files(plugin_id: str, version: str, manifest_id: str | None = None) -> dict[str, bytes]:
    mid = manifest_id or plugin_id
    return {
        "plugin.json": json.dumps({
            "schemaVersion": 1, "id": mid, "name": mid, "version": version,
            "minHostVersion": "0.2.0", "entry": "index.js",
            "capabilities": ["http"], "kinds": ["short"],
            "feeds": [{"id": "main", "name": "主源"}],
        }, ensure_ascii=False).encode("utf-8"),
        "index.js": ("module.exports={id:%r,version:%r,pull:async()=>({items:[]})};"
                     % (mid, version)).encode("utf-8"),
    }


class Sandbox:
    """registry / 远端文件 / 插件目录全在临时目录，其余走真实代码。"""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="of-market-guard-sb-"))
        self.plugin_root = self.root / "plugins"
        self.plugin_root.mkdir(parents=True, exist_ok=True)
        self.remote: dict[str, dict[str, bytes]] = {}
        self.registry_entries: list[dict] = []

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def add_remote(self, plugin_id: str, version: str, manifest_id: str | None = None,
                   sha: bool = True) -> dict:
        files = plugin_files(plugin_id, version, manifest_id)
        self.remote[plugin_id] = files
        pkg = self.root / "pkg" / plugin_id
        if pkg.exists():
            shutil.rmtree(pkg)
        for name, blob in files.items():
            (pkg / name).parent.mkdir(parents=True, exist_ok=True)
            (pkg / name).write_bytes(blob)
        entry = {
            "id": plugin_id, "name": plugin_id, "version": version,
            "description": "测试插件", "author": "test", "kinds": ["short"],
            "capabilities": ["http"], "features": [], "feeds": ["main"],
        }
        if sha:
            entry["sha256"] = market.dir_hash(pkg)
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


def restore_market(saved: list) -> None:
    market.registry = saved["registry"]
    market._remote_files = saved["remote"]
    market._http_bytes = saved["http"]
    market.plugins_root = saved["plugins_root"]


# ---------------------------------------------------------------- registry 协议

def case_registry_scheme() -> None:
    check(market._check_registry_url("https://cdn.example/registry.json").startswith("https"),
          "https 放行")
    check(market._check_registry_url("http://127.0.0.1:8765/registry.json").startswith("http"),
          "本机 IPv4 回环 http 放行（本地开发）")
    check(market._check_registry_url("http://localhost:8765/registry.json").startswith("http"),
          "localhost http 放行")
    expect_raise(lambda: market._check_registry_url("http://evil.example/registry.json"),
                 "公网 http registry 拒绝", "https")
    expect_raise(lambda: market._check_registry_url("ftp://evil.example/registry.json"),
                 "非 http(s) registry 拒绝", "https")
    expect_raise(lambda: market._check_registry_url(""), "空 registry 地址拒绝", "https")

    # 明文 registry 不联网取，降级原因写清楚
    saved_url, saved_http = market.registry_url, market._http_bytes
    calls: list = []

    def fake_http(url: str, timeout: float = 15.0) -> bytes:
        calls.append(url)
        return b'{"plugins":[]}'

    market.registry_url = lambda: "http://evil.example/registry.json"
    market._http_bytes = fake_http
    try:
        data = market.registry(force=True)
        check(data.get("plugins") == [], "明文 registry 不返回任何条目")
        check("https" in str(data.get("degraded")), "降级原因说明必须走 https")
        check(not calls, "明文 registry 没有发起请求")
    finally:
        market.registry_url, market._http_bytes = saved_url, saved_http

    # 本机回环 http registry 照常可用
    market.registry_url = lambda: "http://127.0.0.1:8765/registry.json"
    market._http_bytes = lambda url, timeout=15.0: b'{"plugins":[{"id":"demo","version":"0.1.0"}]}'
    try:
        data = market.registry(force=True)
        check([e["id"] for e in data.get("plugins", [])] == ["demo"], "回环 http registry 可用")
    finally:
        market.registry_url, market._http_bytes = saved_url, saved_http


# ---------------------------------------------------------------- 安装前置校验

def case_missing_sha() -> None:
    sb = Sandbox()
    saved = patch_market(sb)
    store = Store(Path(_TMP_STATE) / "market-guard.db")
    try:
        sb.add_remote("demo", "0.1.0", sha=False)
        expect_raise(lambda: market.install(store, "demo"), "缺 sha256 拒装", "sha256")
        check(not (sb.plugin_root / "demo").exists(), "缺 sha256 时没有换入目录")
        check(store.list_plugins() == [], "缺 sha256 时没有写库")

        sb.add_remote("blank", "0.1.0")
        entry = next(e for e in sb.registry_entries if e["id"] == "blank")
        entry["sha256"] = "   "
        expect_raise(lambda: market.install(store, "blank"), "空白 sha256 也拒装", "sha256")
        check(not (sb.plugin_root / "blank").exists(), "空白 sha256 时没有换入目录")
        check(store.list_plugins() == [], "空白 sha256 时没有写库")

        # 明文 registry 即使有缓存/条目，install 也不放行
        saved_url = market.registry_url
        market.registry_url = lambda: "http://evil.example/registry.json"
        try:
            expect_raise(lambda: market.install(store, "demo"),
                         "明文 registry 的条目拒绝安装", "https")
        finally:
            market.registry_url = saved_url
        check(store.list_plugins() == [], "明文 registry 时没有写库")
    finally:
        store.close()
        restore_market(saved)
        sb.cleanup()


def case_manifest_id_mismatch() -> None:
    sb = Sandbox()
    saved = patch_market(sb)
    store = Store(Path(_TMP_STATE) / "market-guard-id.db")
    try:
        sb.add_remote("demo", "0.1.0", manifest_id="imposter")
        expect_raise(lambda: market.install(store, "demo"), "清单 id 不一致拒装", "不符")
        check(not (sb.plugin_root / "demo").exists(), "id 不一致时没有换入目录")
        check(list(sb.plugin_root.iterdir()) == [], "插件根里没有半成品")
        check(store.list_plugins() == [], "id 不一致时没有写库")
    finally:
        store.close()
        restore_market(saved)
        sb.cleanup()


def case_install_update() -> None:
    sb = Sandbox()
    saved = patch_market(sb)
    store = Store(Path(_TMP_STATE) / "market-guard-ok.db")
    try:
        entry = sb.add_remote("demo", "0.1.0")
        result = market.install(store, "demo")
        check(result["ok"] is True and result["sha256"] == entry["sha256"], "正常安装成功并回带 sha")
        check((sb.plugin_root / "demo" / "plugin.json").exists(), "目录换入")
        check(next(p for p in store.list_plugins() if p["id"] == "demo")["version"] == "0.1.0",
              "库记录是 0.1.0")

        sb.add_remote("demo", "0.2.0")
        upd = market.update(store, "demo")
        check(upd["changed"] is True and upd["to"] == "0.2.0", "正常更新到 0.2.0")
        check(next(p for p in store.list_plugins() if p["id"] == "demo")["version"] == "0.2.0",
              "库记录跟着更新")

        # 新版条目被抽掉 sha256：更新也要拒，旧版本必须还在
        sb.add_remote("demo", "0.3.0", sha=False)
        expect_raise(lambda: market.update(store, "demo"), "更新同样拒缺 sha256", "sha256")
        check(next(p for p in store.list_plugins() if p["id"] == "demo")["version"] == "0.2.0",
              "拒装后库记录仍是 0.2.0")
        manifest = json.loads((sb.plugin_root / "demo" / "plugin.json").read_text(encoding="utf-8"))
        check(manifest["version"] == "0.2.0", "拒装后磁盘上仍是 0.2.0")
    finally:
        store.close()
        restore_market(saved)
        sb.cleanup()


def main() -> int:
    case_registry_scheme()
    case_missing_sha()
    case_manifest_id_mismatch()
    case_install_update()
    print(f"✅ test_market_guard.py  OF-36 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
