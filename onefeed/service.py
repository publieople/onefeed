"""采集编排（003 T37）与离线演示数据（T49）。

一个进程里同时只有一个采集任务；重复触发返回 409，不排队。
DEMO 模式下不联网，直接从 fixtures/<plugin>.json 读上次抓到的条目。
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

from plugin_runtime.host import PluginHost, default_plugins_dir

from . import market, settings as settings_mod, smart

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "fixtures"


def demo_mode() -> bool:
    return os.environ.get("ONEFEED_DEMO") == "1"


def _item_id(it: Any) -> str:
    """插件交回来的是 Item 对象，演示模式读的是 dict，两种都要能取 id。

    之前这里只认 dict，导致 fresh 恒为 0、状态条永远说「+0 条」——库其实在长。
    """
    if isinstance(it, dict):
        return str(it.get("id") or "")
    return str(getattr(it, "id", "") or "")


class FixtureMissing(RuntimeError):
    """DEMO 模式下这个平台没有本地样例。算「跳过」，不算抓取失败。"""


def sync_installed(store, root: Path | None = None) -> int:
    """把插件目录里真实存在的插件登记进库：目录是事实，库只是索引。

    库里没有的补一条 source=local；库里多出来的（目录已被手工删掉）不主动删，
    交给卸载接口处理，免得误删历史记录。
    """
    root = Path(root or default_plugins_dir())
    if not root.is_dir():
        return 0
    known = {p["id"] for p in store.list_plugins()}
    added = 0
    for child in sorted(root.iterdir()):
        try:
            if not child.is_dir():
                continue
            manifest_path = child / "plugin.json"
            if not manifest_path.exists():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 单个插件目录读不动（权限坏了、正在被卸载、半截文件）不该拖垮启动：
            # 跳过它，其余插件照常登记，缺的那一个由插件页单独报错。
            continue
        plugin_id = str(manifest.get("id") or child.name)
        if plugin_id in known:
            continue
        store.upsert_plugin(plugin_id, str(manifest.get("version", "")), source="local")
        added += 1
    return added


class RefreshRunner:
    def __init__(self, store, host: PluginHost | None = None, limit: int = 12,
                 prune_days: int = 14, auto_update: bool = False) -> None:
        self.store = store
        self.host = host or PluginHost()
        self.limit = limit
        self.prune_days = prune_days
        self.auto_update = auto_update
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "running": False, "started_at": 0, "finished_at": 0,
            "done": 0, "total": 0, "plugins": {}, "error": "",
            # 前端只看 running 会把「抓完了但还在 prune/cluster」误判成已完成，
            # 于是列表在整理落地前就被重取一遍。phase 把这一小段说清楚。
            "phase": "idle", "new_total": 0,
        }

    # ------------------------------------------------------------ 对外
    def plugin_ids(self) -> list[str]:
        return [m.id for m in self.host.discover()]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def running(self) -> bool:
        with self._lock:
            return bool(self._state["running"])

    def _cooldown(self, pid: str, now: int) -> int:
        """还要等多少秒才能抓这个平台（0 = 可以抓）。"""
        interval = int(settings_mod.platform_intervals().get(pid, 0))
        if interval <= 0:
            return 0
        last = self.store.last_pull_at(pid)
        if not last:
            return 0
        return max(0, last + interval - now)

    def trigger(self, platforms: Iterable[str] | None = None,
                warmup: bool = False, force: bool = False) -> tuple[bool, dict[str, Any]]:
        """返回 (是否真的启动, 当前状态)。已在跑时返回 (False, 状态)。

        force=True 跳过平台冷却（用户明确要求「现在就抓」时用）。
        冷却是按平台算的，不是整轮算：B 站刚抓过，不该拦住知乎。
        """
        with self._lock:
            if self._state["running"]:
                return False, json.loads(json.dumps(self._state))
            # 平台展示名跟着清单走：前端不必再维护一份 id→中文名 的映射
            # （原来散在 TabRail 与状态条两处，加一个平台要改两个文件）。
            labels = {m.id: (m.name or m.id) for m in self.host.discover()}
            ids = [p for p in (platforms or list(labels)) if p]
            if not ids:
                self._state.update({"error": "没有可用的插件", "finished_at": int(time.time()),
                                    "phase": "idle"})
                return False, json.loads(json.dumps(self._state))
            now = int(time.time())
            # 演示模式不联网，冷却没有意义；warmup 是显式补样例，也不该被拦
            cooling = {} if (force or warmup or demo_mode()) else {
                pid: self._cooldown(pid, now) for pid in ids
            }
            plugins: dict[str, Any] = {}
            for pid in ids:
                wait = int(cooling.get(pid, 0))
                if wait > 0:
                    plugins[pid] = {
                        "status": "skipped", "count": 0, "new_count": 0, "error": "", "ms": 0,
                        "label": labels.get(pid, pid),
                        "next_at": now + wait,
                        "note": f"平台冷却中，还要等 {wait} 秒",
                    }
                else:
                    plugins[pid] = {"status": "queued", "count": 0, "new_count": 0,
                                    "error": "", "ms": 0, "label": labels.get(pid, pid)}
            active = [pid for pid in ids if plugins[pid]["status"] == "queued"]
            self._state = {
                "running": bool(active), "started_at": now,
                "finished_at": 0 if active else now,
                "done": len(ids) - len(active), "total": len(ids),
                "error": "" if active else "都在平台冷却中，这一轮没有实际抓取",
                "phase": "fetching" if active else "empty",
                "new_total": 0,
                "warmup": warmup,
                "market": {"checked": 0, "updated": [], "failed": []},
                "plugins": plugins,
            }
            if active:
                self._thread = threading.Thread(target=self._run, args=(active, warmup),
                                                name="onefeed-refresh", daemon=True)
                self._thread.start()
            return True, json.loads(json.dumps(self._state))

    # ------------------------------------------------------------ 内部
    def _set(self, pid: str, **fields: Any) -> None:
        with self._lock:
            entry = self._state["plugins"].setdefault(pid, {})
            entry.update(fields)
            if fields.get("status") in ("ok", "failed", "skipped"):
                self._state["done"] = sum(
                    1 for p in self._state["plugins"].values()
                    if p.get("status") in ("ok", "failed", "skipped"))

    def _run(self, ids: list[str], warmup: bool) -> None:
        try:
            with self._lock:
                self._state["phase"] = "fetching"
            if self.auto_update and not demo_mode():
                # 采集前先问一次 registry（走 1h 缓存，不会每轮都打网络）。
                # 装了新版要重新发现插件，否则这一轮还是旧 manifest。
                try:
                    result = market.update_all(self.store)
                    with self._lock:
                        self._state["market"] = {
                            "checked": result.get("checked", 0),
                            "updated": result.get("updated", []),
                            "failed": result.get("failed", []),
                        }
                    if result.get("updated"):
                        self.host.discover()
                except Exception as exc:  # 更新失败不该拖垮采集
                    with self._lock:
                        self._state["market"] = {"checked": 0, "updated": [],
                                                 "failed": [{"id": "registry",
                                                             "error": f"{type(exc).__name__}: {exc}"[:160]}]}
            for pid in ids:
                started = time.time()
                self._set(pid, status="running")
                run_id = self.store.start_run(pid, demo=demo_mode())
                try:
                    items = self._load(pid)
                    # upsert 的 rowcount 只是「受影响行数」，分不出新插入与只更新了统计。
                    # 结果文案要说「这一轮新增 N 条」，所以入库前先拿一次已有 id。
                    known = self.store.item_ids(_item_id(it) for it in items)
                    fresh = sum(1 for it in items if _item_id(it) not in known)
                    count = self.store.upsert_items(items)
                    if warmup:
                        self._dump(pid, items)
                    self.store.finish_run(run_id, True, count)
                    self._set(pid, status="ok", count=count, new_count=fresh,
                              ms=int((time.time() - started) * 1000))
                    with self._lock:
                        self._state["new_total"] = int(self._state.get("new_total") or 0) + fresh
                except FixtureMissing as exc:  # 演示模式没导出这个平台：跳过就好，不必报警
                    self.store.finish_run(run_id, False, 0, str(exc))
                    self._set(pid, status="skipped", note=str(exc), count=0,
                              ms=int((time.time() - started) * 1000))
                except Exception as exc:  # 单个插件失败不影响其它平台
                    tb = traceback.format_exc().strip().splitlines()
                    tail = " | ".join(tb[-3:]) if tb else ""
                    reason = f"{type(exc).__name__}: {exc} | {tail}"[:600]
                    self.store.finish_run(run_id, False, 0, reason)
                    self._set(pid, status="failed", error=reason,
                              ms=int((time.time() - started) * 1000))
            # 平台都跑完了，但整理还没落地：这一小段必须有自己的 phase，
            # 否则前端一看到 running=false 就重取列表，排序会在整理完成前闪一下。
            with self._lock:
                self._state["phase"] = "settling"
            try:
                self.store.prune(keep_days=self.prune_days)
                smart.cluster(self.store)
            except Exception:
                pass
        finally:
            with self._lock:
                plugins = self._state.get("plugins") or {}
                failed = any(p.get("status") == "failed" for p in plugins.values())
                ok = any(p.get("status") == "ok" for p in plugins.values())
                # 有失败就是 partial：结果仍可用，只是缺一两个平台
                self._state["phase"] = "partial" if failed else ("done" if ok else "empty")
                self._state["running"] = False
                self._state["finished_at"] = int(time.time())

    def _load(self, pid: str) -> list[dict[str, Any]]:
        if demo_mode():
            path = FIXTURES_DIR / f"{pid}.json"
            if not path.exists():
                raise FixtureMissing(
                    f"演示模式没有 {path.name} 的样例（在线跑一次 --warmup 就能补上）")
            data = json.loads(path.read_text(encoding="utf-8"))
            return [it for it in data.get("items", []) if isinstance(it, dict)]
        return self.host.pull(pid, limit=self.limit)

    def _dump(self, pid: str, items: Iterable[Any]) -> None:
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        rows = [it.to_dict() if hasattr(it, "to_dict") else dict(it) for it in items]
        safe = []
        for row in rows:
            row = dict(row)
            row.pop("cookie", None)
            safe.append(row)
        payload = {"plugin": pid, "saved_at": int(time.time()), "items": safe}
        (FIXTURES_DIR / f"{pid}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")