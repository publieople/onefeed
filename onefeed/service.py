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

from . import market, smart

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "fixtures"


def demo_mode() -> bool:
    return os.environ.get("ONEFEED_DEMO") == "1"


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
        manifest_path = child / "plugin.json"
        if not child.is_dir() or not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
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

    def trigger(self, platforms: Iterable[str] | None = None,
                warmup: bool = False) -> tuple[bool, dict[str, Any]]:
        """返回 (是否真的启动, 当前状态)。已在跑时返回 (False, 状态)。"""
        with self._lock:
            if self._state["running"]:
                return False, json.loads(json.dumps(self._state))
            ids = [p for p in (platforms or self.plugin_ids()) if p]
            if not ids:
                self._state.update({"error": "没有可用的插件", "finished_at": int(time.time())})
                return False, json.loads(json.dumps(self._state))
            self._state = {
                "running": True, "started_at": int(time.time()), "finished_at": 0,
                "done": 0, "total": len(ids), "error": "", "warmup": warmup,
                "market": {"checked": 0, "updated": [], "failed": []},
                "plugins": {pid: {"status": "queued", "count": 0, "error": "", "ms": 0}
                            for pid in ids},
            }
            self._thread = threading.Thread(target=self._run, args=(ids, warmup),
                                            name="onefeed-refresh", daemon=True)
            self._thread.start()
            return True, json.loads(json.dumps(self._state))

    # ------------------------------------------------------------ 内部
    def _set(self, pid: str, **fields: Any) -> None:
        with self._lock:
            entry = self._state["plugins"].setdefault(pid, {})
            entry.update(fields)
            if fields.get("status") in ("ok", "failed"):
                self._state["done"] = sum(
                    1 for p in self._state["plugins"].values()
                    if p.get("status") in ("ok", "failed"))

    def _run(self, ids: list[str], warmup: bool) -> None:
        try:
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
                run_id = self.store.start_run(pid)
                try:
                    items = self._load(pid)
                    count = self.store.upsert_items(items)
                    if warmup:
                        self._dump(pid, items)
                    self.store.finish_run(run_id, True, count)
                    self._set(pid, status="ok", count=count,
                              ms=int((time.time() - started) * 1000))
                except Exception as exc:  # 单个插件失败不影响其它平台
                    tb = traceback.format_exc().strip().splitlines()
                    tail = " | ".join(tb[-3:]) if tb else ""
                    reason = f"{type(exc).__name__}: {exc} | {tail}"[:600]
                    self.store.finish_run(run_id, False, 0, reason)
                    self._set(pid, status="failed", error=reason,
                              ms=int((time.time() - started) * 1000))
            try:
                self.store.prune(keep_days=self.prune_days)
                smart.cluster(self.store)
            except Exception:
                pass
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["finished_at"] = int(time.time())

    def _load(self, pid: str) -> list[dict[str, Any]]:
        if demo_mode():
            path = FIXTURES_DIR / f"{pid}.json"
            if not path.exists():
                raise RuntimeError(f"DEMO 模式下没有 {path.name}，先在线跑一次 --warmup")
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