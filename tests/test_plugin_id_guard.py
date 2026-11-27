"""OF-04 / OF-37 验收：插件 id 当目录名用之前必须校验。

跑法：
    python tests/test_plugin_id_guard.py

OF-04：DELETE /api/plugins/%2E 把 plugin_id="." 直接拼进插件目录，把整个插件根
改名"卸载"掉。OF-37：install / update 走同一条 target_root / plugin_id，缺同一道校验。
这里只验校验层与拦截路径，不联网、不下载。
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP_STATE = Path(tempfile.mkdtemp(prefix="of-plugin-id-"))
os.environ["ONEFEED_HOME"] = str(_TMP_STATE)


def _drop_tmp_state() -> None:
    import gc
    import time

    gc.collect()
    for _ in range(4):
        shutil.rmtree(_TMP_STATE, ignore_errors=True)
        if not _TMP_STATE.exists():
            return
        time.sleep(0.15)


atexit.register(_drop_tmp_state)

from fastapi.testclient import TestClient  # noqa: E402

from onefeed import market  # noqa: E402
from onefeed.app import create_app  # noqa: E402
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


def expect_raise(fn, label: str, exc_type: type = Exception) -> Exception:
    global CHECKS
    try:
        fn()
    except exc_type as exc:
        CHECKS += 1
        if VERBOSE:
            print(f"  ok  {label}")
        return exc
    except Exception as exc:  # 类型不对也算失败，消息里带上实际类型
        raise AssertionError(f"{label}（抛了 {type(exc).__name__}: {exc}，期望 {exc_type.__name__}）")
    raise AssertionError(label + "（应当报错但没有）")


# ---------------------------------------------------------------- 纯函数层

GOOD_IDS = ["bilibili", "xiaohongshu", "demo", "a1", "of-plugin", "p" * 32]
BAD_IDS = ["", ".", "..", "...", "../x", "..\\x", "a/b", "a\\b", "%2E", "%2e%2e",
           "Bilibili", "1abc", "a", "a b", "a.b", "bili\tm", "p" * 33, "插件", "a\x00b",
           # T4 F1：re.match + $ 会放过末尾换行，必须 fullmatch 才算合法 id
           "bilibili\n", "bilibili\n\n"]


def case_validate_id() -> None:
    for pid in GOOD_IDS:
        check(market.validate_plugin_id(pid) == pid, f"合法 id 原样返回：{pid!r}")
    for pid in BAD_IDS:
        expect_raise(lambda p=pid: market.validate_plugin_id(p),
                     f"非法 id 被拒：{pid!r}", market.InvalidPluginId)
    # 与清单同一套规则：装进去的目录名必须是宿主能加载的 id
    from plugin_runtime.manifest import ID_RE, validate_manifest
    check(market.ID_RE is ID_RE, "market 的 id 规则和清单是同一份（不各写一遍）")
    manifest = {
        "schemaVersion": 1, "id": "bilibili\n", "name": "B 站", "version": "1.0.0",
        "minHostVersion": "0.2.0", "entry": "index.js", "capabilities": ["http"],
        "kinds": ["list"], "feeds": [{"id": "main", "name": "主源"}],
    }
    errors = validate_manifest(manifest)
    check(any("id 必填" in e for e in errors), "清单校验同样拒末尾换行 id")
    manifest["id"] = "bilibili"
    errors = validate_manifest(manifest)
    check(errors == [], f"同一份清单换成合法 id 后没有报错（实际：{errors}）")
    check(issubclass(market.InvalidPluginId, ValueError), "InvalidPluginId 是 ValueError 子类")
    expect_raise(lambda: market.validate_plugin_id(None), "None 当 id 被拒",
                 market.InvalidPluginId)


def case_plugin_target(tmp: Path) -> None:
    root = tmp / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    check(market.plugin_target(root, "bilibili") == root / "bilibili", "插件目录 = 根 / id")
    # 根里带 .. 段也照样落在解析后的根下一层（resolve 之后比较）
    weird = tmp / "plugins" / "nested" / ".."
    target = market.plugin_target(weird, "demo")
    check(target.name == "demo", "带 .. 的插件根：目录名仍是 id")
    check(target.parent.resolve() == root.resolve(), "带 .. 的插件根：父目录解析后就是根")
    for pid in (".", "..", "../x", "a/b"):
        expect_raise(lambda p=pid: market.plugin_target(root, p),
                     f"插件目录不接受穿越 id：{pid!r}", market.InvalidPluginId)
    check(not (tmp / "x").exists(), "穿越 id 没有在根外造出东西")


# ---------------------------------------------------------------- 市场层

class FakeStore:
    """市场层只用到「列已装 / 删库记录」；不该走到写库。"""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.plugins: list[dict] = []

    def list_plugins(self) -> list[dict]:
        return list(self.plugins)

    def delete_plugin(self, plugin_id: str) -> None:
        self.deleted.append(plugin_id)

    def upsert_plugin(self, *args, **kwargs) -> None:
        raise AssertionError("校验失败的调用不该写库")


def write_plugin(plugin_root: Path, plugin_id: str) -> None:
    path = plugin_root / plugin_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "plugin.json").write_text(json.dumps({
        "schemaVersion": 1, "id": plugin_id, "name": plugin_id, "version": "1.0.0",
        "minHostVersion": "0.2.0", "entry": "index.js",
        "capabilities": [], "kinds": ["list"],
        "feeds": [{"id": "main", "name": "主源"}],
    }, ensure_ascii=False), encoding="utf-8")
    (path / "index.js").write_text("module.exports={};", encoding="utf-8")


def case_market_guard(tmp: Path) -> None:
    sb = tmp / "market-sandbox"
    plugin_root = sb / "plugins"
    write_plugin(plugin_root, "bilibili")
    sibling = sb / "sibling"
    sibling.mkdir(parents=True, exist_ok=True)
    (sibling / "keep.txt").write_text("keep", encoding="utf-8")
    store = FakeStore()

    with mock.patch.object(market, "plugins_root", lambda: plugin_root):
        # OF-04：卸载入口先校验，插件根与其它目录都必须原样留着
        for pid in (".", "..", "../x", "%2E"):
            expect_raise(lambda p=pid: market.uninstall(store, p),
                         f"uninstall 拒绝穿越 id：{pid!r}", market.InvalidPluginId)
        check(plugin_root.is_dir(), "插件根还在（没有被整个 rename 走）")
        check((plugin_root / "bilibili" / "plugin.json").exists(), "插件目录还在")
        check((sibling / "keep.txt").exists(), "插件根的同级目录没被动过")
        check(store.deleted == [], "校验失败不写库")

        # OF-37：install / update 同一条 target_root / plugin_id，同一道校验
        for pid in (".", "..", "a/b"):
            expect_raise(lambda p=pid: market.install(store, p),
                         f"install 拒绝穿越 id：{pid!r}", market.InvalidPluginId)
            expect_raise(lambda p=pid: market.update(store, p),
                         f"update 拒绝穿越 id：{pid!r}", market.InvalidPluginId)

        # 合法 id 照常往下走：不是靠「先报错」蒙过去的
        with mock.patch.object(market, "merged", lambda store_, force=False: {"entries": []}):
            exc = expect_raise(lambda: market.install(store, "demo"),
                               "合法 id 通过校验，走到 registry 查找", RuntimeError)
        check("registry 里没有 demo" in str(exc), "合法 id 的报错来自 registry 而不是 id 校验")
        exc = expect_raise(lambda: market.update(store, "demo"),
                           "合法 id 的 update 走到「还没装」", RuntimeError)
        check("还没装" in str(exc), "update 的报错来自安装状态而不是 id 校验")

    check(sibling.is_dir(), "离开沙箱后同级目录仍在")


# ---------------------------------------------------------------- 接口层

def _err(resp) -> dict:
    """宿主把 HTTPException 统一包成 {"error": {...}}；老接口也有 detail 形态。"""
    body = resp.json()
    return body.get("error") or body.get("detail") or {}


def case_api_guard(tmp: Path) -> None:
    plugin_root = tmp / "api-sandbox" / "plugins"
    write_plugin(plugin_root, "bilibili")
    store = Store(tmp / "api-sandbox" / "api.db")
    try:
        client = TestClient(create_app(store, plugins_dir=plugin_root))
        with mock.patch.object(market, "plugins_root", lambda: plugin_root):
            for method, path in (("delete", "/api/plugins/%2E"),
                                 ("post", "/api/plugins/%2E/install"),
                                 ("post", "/api/plugins/%2E/update")):
                resp = getattr(client, method)(path)
                check(resp.status_code == 400, f"{method.upper()} {path} 返回 400（实际 {resp.status_code}）")
                detail = _err(resp)
                check(detail.get("code") == "invalid_plugin_id",
                      f"{method.upper()} {path} 报 invalid_plugin_id（实际 {detail.get('code')}）")
                check("hint" in detail, f"{method.upper()} {path} 带 hint")
            # .. 也一样，不能靠编码绕过
            resp = client.delete("/api/plugins/%2E%2E")
            check(resp.status_code == 400, "DELETE %2E%2E 也是 400")
            check(_err(resp).get("code") == "invalid_plugin_id", "DELETE %2E%2E 报 invalid_plugin_id")

            # T4 F1：%0A 解码成末尾换行，旧实现会放行到 uninstall（200 removed=false）
            resp = client.delete("/api/plugins/bilibili%0A")
            check(resp.status_code == 400, f"DELETE bilibili%0A 返回 400（实际 {resp.status_code}）")
            check(_err(resp).get("code") == "invalid_plugin_id", "末尾换行 id 报 invalid_plugin_id")
            check((plugin_root / "bilibili" / "plugin.json").exists(), "带换行的 DELETE 没删到 bilibili")

            # 拦截之后现场必须完好：插件根、已装插件、库里的记录都还在
            check(plugin_root.is_dir(), "接口拦截后插件根还在")
            check((plugin_root / "bilibili" / "plugin.json").exists(), "接口拦截后插件目录还在")
            check(any(p["id"] == "bilibili" for p in store.list_plugins()),
                  "接口拦截后库里还有 bilibili")

            # 合法 id 仍然走真实逻辑：没装过的 id 只是「没删到东西」，不是 400
            resp = client.delete("/api/plugins/nosuch")
            check(resp.status_code == 200, f"合法 id 的 DELETE 仍是 200（实际 {resp.status_code}）")
            check(resp.json().get("result", {}).get("removed") is False, "没装过的 id 回 removed=False")
    finally:
        store.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="of-plugin-id-case-"))
    try:
        case_validate_id()
        case_plugin_target(tmp)
        case_market_guard(tmp)
        case_api_guard(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"plugin_id_guard ok（{CHECKS} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
