"""关注流同步器（2026-11-24）。

和主信息流的 RefreshRunner 刻意分开：
- 主信息流问的是「平台今天推荐什么」，关注流问的是「我关注的人发了什么」，
  两条流的冷却、失败、进度都不该互相污染；
- 关注流是个人化数据，必须登录，抓取更慢，不能跟着顶栏刷新按钮一起跑；
- 状态只在关注页里说，主信息流的刷新演出不知道它存在。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Iterable

from plugin_runtime.host import PluginHost

from . import smart

FOLLOWING_FEED = "following"
# 关注流比推荐流更费账号：同一个平台 5 分钟内只同步一次，避免用户连点把账号送进风控。
FOLLOWING_COOLDOWN = 300
# 前端轮询阈值：超过这个时间没有心跳，就认为这一轮卡住了。
FOLLOWING_STALE = 600


def _item_ids(items: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for it in items:
        data = it.to_dict() if hasattr(it, "to_dict") else dict(it)
        item_id = str(data.get("id") or "")
        if item_id:
            out.append(item_id)
    return out


class FollowingRunner:
    def __init__(self, store, host: PluginHost | None = None, limit: int = 12) -> None:
        self.store = store
        self.host = host or PluginHost()
        self.limit = max(1, min(int(limit), 50))
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "running": False, "started_at": 0, "finished_at": 0,
            "done": 0, "total": 0, "plugins": {}, "error": "",
            "phase": "idle", "new_total": 0, "cancelled": 0,
            "source": "user", "owner": "", "cancel_requested": False,
            "feed": FOLLOWING_FEED,
        }

    # ------------------------------------------------------------ 对外
    def manifests(self) -> list[Any]:
        try:
            return self.host.discover()
        except Exception:
            return []

    def platform_ids(self) -> list[str]:
        return [m.id for m in self.manifests() if FOLLOWING_FEED in m.feed_ids()]

    def supports(self, plugin_id: str) -> bool:
        return any(m.id == plugin_id and FOLLOWING_FEED in m.feed_ids()
                   for m in self.manifests())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def running(self) -> bool:
        with self._lock:
            return bool(self._state["running"])

    def last_runs(self) -> dict[str, dict[str, Any]]:
        return self.store.following_run_stats(FOLLOWING_FEED)

    def cooldown_left(self, plugin_id: str) -> int:
        stat = self.last_runs().get(plugin_id) or {}
        last = int(stat.get("last_run_at") or 0)
        if not last:
            return 0
        return max(0, FOLLOWING_COOLDOWN - (int(time.time()) - last))

    def trigger(self, platforms: list[str] | None = None, force: bool = False,
                source: str = "user", owner: str = "") -> tuple[bool, dict[str, Any]]:
        """开始一轮关注流同步；已经在跑就返回 False，不排队。"""
        with self._lock:
            if self._state["running"]:
                if self._state.get("owner") != owner or not owner:
                    self._state["error"] = "关注流正在同步，等这一轮跑完"
                return False, json.loads(json.dumps(self._state))

            manifests = self.manifests()
            supported = {m.id: m for m in manifests if FOLLOWING_FEED in m.feed_ids()}
            wanted = [str(x) for x in (platforms or []) if str(x)]
            if wanted:
                missing = [pid for pid in wanted if pid not in supported]
                active = [pid for pid in wanted if pid in supported]
            else:
                missing = []
                active = list(supported)
            if not active:
                self._state.update({
                    "running": False, "phase": "empty", "started_at": 0,
                    "finished_at": int(time.time()), "done": 0, "total": 0,
                    "plugins": {}, "new_total": 0, "cancelled": 0,
                    "error": ("这些平台还没有关注流支持" if missing
                              else "没有可同步的关注流插件"),
                    "source": source, "owner": owner, "cancel_requested": False,
                })
                return False, json.loads(json.dumps(self._state))

            stats = self.last_runs()
            cooling = []
            if not force:
                for pid in active:
                    last = int((stats.get(pid) or {}).get("last_run_at") or 0)
                    if last and int(time.time()) - last < FOLLOWING_COOLDOWN:
                        cooling.append(pid)
                active = [pid for pid in active if pid not in cooling]
            if not active:
                # 只按这次真正要同步的平台算，别把没请求的平台的剩余冷却也算进来
                left = min(self.cooldown_left(pid) for pid in cooling) if cooling else 0
                self._state.update({
                    "running": False, "phase": "empty", "started_at": 0,
                    "finished_at": int(time.time()), "done": 0, "total": 0,
                    "plugins": {}, "new_total": 0, "cancelled": 0,
                    "error": f"平台冷却中，{max(1, left // 60)} 分钟后再同步",
                    "source": source, "owner": owner, "cancel_requested": False,
                })
                return False, json.loads(json.dumps(self._state))

            labels = {m.id: (m.name or m.id) for m in manifests}
            self._state = {
                "running": True, "started_at": int(time.time()), "finished_at": 0,
                "done": 0, "total": len(active),
                "plugins": {pid: {"status": "queued", "count": 0, "new_count": 0,
                                  "label": labels.get(pid, pid), "error": "", "ms": 0}
                            for pid in active},
                "error": "", "phase": "fetching", "new_total": 0, "cancelled": 0,
                "source": source, "owner": owner, "cancel_requested": False,
                "feed": FOLLOWING_FEED,
            }
            self._thread = threading.Thread(target=self._run, args=(active,),
                                            name="onefeed-following", daemon=True)
            self._thread.start()
            return True, json.loads(json.dumps(self._state))

    def cancel(self, owner: str | None = None) -> bool:
        """协作式取消：置位后不再开新平台，当前平台跑完就停。"""
        with self._lock:
            if not self._state["running"]:
                return False
            current = str(self._state.get("owner") or "")
            # 带 owner 的取消只认自己那一轮；current 为空是用户手点的，不能让 Agent 顺手停掉
            if owner and current != owner:
                return False
            self._state["cancel_requested"] = True
            for row in self._state["plugins"].values():
                if row.get("status") == "queued":
                    row["status"] = "cancelled"
                    self._state["cancelled"] += 1
            return True

    # ------------------------------------------------------------ 线程内
    def _set(self, pid: str, **fields: Any) -> None:
        with self._lock:
            row = self._state["plugins"].setdefault(pid, {})
            row.update(fields)
            self._state["done"] = sum(
                1 for p in self._state["plugins"].values()
                if p.get("status") in ("ok", "failed", "skipped", "cancelled"))

    def _run(self, active: list[str]) -> None:
        failed = 0
        cancelled = 0
        try:
            for pid in active:
                with self._lock:
                    if self._state["cancel_requested"]:
                        row = self._state["plugins"].get(pid) or {}
                        if row.get("status") == "queued":
                            row["status"] = "cancelled"
                            self._state["cancelled"] += 1
                        cancelled += 1
                        continue
                    if (self._state["plugins"].get(pid) or {}).get("status") == "cancelled":
                        cancelled += 1
                        continue
                self._set(pid, status="running")
                run_id = self.store.start_following_run(pid, FOLLOWING_FEED)
                started = time.time()
                try:
                    items = self._load(pid)
                    known = self.store.item_ids(_item_ids(items))
                    fresh = sum(1 for i in _item_ids(items) if i not in known)
                    if items:
                        self.store.upsert_items(items)
                        self.store.mark_feed_items(items, FOLLOWING_FEED)
                    self.store.finish_following_run(run_id, True, len(items), fresh)
                    self._set(pid, status="ok", count=len(items), new_count=fresh,
                              ms=int((time.time() - started) * 1000), error="")
                    with self._lock:
                        self._state["new_total"] += fresh
                except Exception as exc:
                    failed += 1
                    message = f"{type(exc).__name__}: {exc}"[:300]
                    self.store.finish_following_run(run_id, False, 0, 0, message)
                    self._set(pid, status="failed", error=message,
                              ms=int((time.time() - started) * 1000))
            with self._lock:
                self._state["phase"] = "settling"
            if not cancelled:
                try:
                    smart.cluster(self.store)
                except Exception:
                    pass
        finally:
            with self._lock:
                state = self._state
                for row in state["plugins"].values():
                    if row.get("status") == "queued":
                        row["status"] = "cancelled"
                        state["cancelled"] += 1
                state["done"] = sum(1 for p in state["plugins"].values()
                                    if p.get("status") in ("ok", "failed", "skipped", "cancelled"))
                state["running"] = False
                state["finished_at"] = int(time.time())
                state["cancel_requested"] = False
                if state["cancelled"] and not failed:
                    state["phase"] = "cancelled"
                elif failed and failed == len(state["plugins"]):
                    state["phase"] = "failed"
                    state["error"] = "这一轮没同步到关注内容"
                elif failed:
                    state["phase"] = "partial"
                    state["error"] = f"{failed} 个平台没同步成功"
                else:
                    state["phase"] = "done"

    def _load(self, pid: str) -> list[Any]:
        if getattr(self.host, "demo", False):
            raise RuntimeError("演示模式没有关注流样例")
        return self.host.pull(pid, feed_id=FOLLOWING_FEED, limit=self.limit)


ACCOUNTS_FEED = "accounts"
# 关注名单变得很慢：半小时一次足够，也把账号风控风险压到最低。
ACCOUNTS_COOLDOWN = 1800
ACCOUNTS_STALE = 600
ACCOUNTS_MAX = 1000


class AccountsRunner:
    """同步「我关注了谁」的名单。

    名单和关注流是两种数据：名单是账号维度、变化慢；关注流是内容维度、变化快。
    两条同步用不同的 feed 标签写 following_runs，互不影响冷却和失败状态，
    也绝不写主信息流的 runs 表。
    """

    def __init__(self, store, host: PluginHost | None = None) -> None:
        self.store = store
        self.host = host or PluginHost()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "running": False, "started_at": 0, "finished_at": 0,
            "done": 0, "total": 0, "plugins": {}, "error": "",
            "phase": "idle", "new_total": 0, "cancelled": 0,
            "source": "user", "owner": "", "cancel_requested": False,
            "feed": ACCOUNTS_FEED, "accounts": 0,
        }

    def manifests(self) -> list[Any]:
        try:
            return self.host.discover()
        except Exception:
            return []

    def platform_ids(self) -> list[str]:
        return [m.id for m in self.manifests() if "following_accounts" in m.features]

    def supports(self, plugin_id: str) -> bool:
        return any(m.id == plugin_id and "following_accounts" in m.features
                   for m in self.manifests())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def running(self) -> bool:
        with self._lock:
            return bool(self._state["running"])

    def last_runs(self) -> dict[str, dict[str, Any]]:
        return self.store.following_run_stats(ACCOUNTS_FEED)

    def cooldown_left(self, plugin_id: str) -> int:
        stat = self.last_runs().get(plugin_id) or {}
        last = int(stat.get("last_run_at") or 0)
        if not last:
            return 0
        return max(0, ACCOUNTS_COOLDOWN - (int(time.time()) - last))

    def trigger(self, platforms: list[str] | None = None, force: bool = False,
                source: str = "user", owner: str = "") -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if self._state["running"]:
                if self._state.get("owner") != owner or not owner:
                    self._state["error"] = "关注名单正在同步，等这一轮跑完"
                return False, json.loads(json.dumps(self._state))

            manifests = self.manifests()
            supported = {m.id: m for m in manifests if "following_accounts" in m.features}
            wanted = [str(x) for x in (platforms or []) if str(x)]
            if wanted:
                missing = [pid for pid in wanted if pid not in supported]
                active = [pid for pid in wanted if pid in supported]
            else:
                missing = []
                active = list(supported)
            if not active:
                self._state.update({
                    "running": False, "phase": "empty", "started_at": 0,
                    "finished_at": int(time.time()), "done": 0, "total": 0,
                    "plugins": {}, "new_total": 0, "cancelled": 0, "accounts": 0,
                    "error": ("这些平台还不支持同步关注名单" if missing
                              else "没有可同步关注名单的插件"),
                    "source": source, "owner": owner, "cancel_requested": False,
                })
                return False, json.loads(json.dumps(self._state))

            stats = self.last_runs()
            cooling: list[str] = []
            if not force:
                for pid in active:
                    last = int((stats.get(pid) or {}).get("last_run_at") or 0)
                    if last and int(time.time()) - last < ACCOUNTS_COOLDOWN:
                        cooling.append(pid)
                active = [pid for pid in active if pid not in cooling]
            if not active:
                # 只按这次真正要同步的平台算，别把没请求的平台的剩余冷却也算进来
                left = min(self.cooldown_left(pid) for pid in cooling) if cooling else 0
                self._state.update({
                    "running": False, "phase": "empty", "started_at": 0,
                    "finished_at": int(time.time()), "done": 0, "total": 0,
                    "plugins": {}, "new_total": 0, "cancelled": 0, "accounts": 0,
                    "error": f"关注名单冷却中，{max(1, left // 60)} 分钟后再同步",
                    "source": source, "owner": owner, "cancel_requested": False,
                })
                return False, json.loads(json.dumps(self._state))

            labels = {m.id: (m.name or m.id) for m in manifests}
            self._state = {
                "running": True, "started_at": int(time.time()), "finished_at": 0,
                "done": 0, "total": len(active),
                "plugins": {pid: {"status": "queued", "count": 0, "new_count": 0,
                                  "label": labels.get(pid, pid), "error": "", "ms": 0}
                            for pid in active},
                "error": "", "phase": "fetching", "new_total": 0, "cancelled": 0,
                "source": source, "owner": owner, "cancel_requested": False,
                "feed": ACCOUNTS_FEED, "accounts": 0,
            }
            self._thread = threading.Thread(target=self._run, args=(active,),
                                            name="onefeed-accounts", daemon=True)
            self._thread.start()
            return True, json.loads(json.dumps(self._state))

    def cancel(self, owner: str | None = None) -> bool:
        with self._lock:
            if not self._state["running"]:
                return False
            current = str(self._state.get("owner") or "")
            # 带 owner 的取消只认自己那一轮；current 为空是用户手点的，不能让 Agent 顺手停掉
            if owner and current != owner:
                return False
            self._state["cancel_requested"] = True
            for row in self._state["plugins"].values():
                if row.get("status") == "queued":
                    row["status"] = "cancelled"
                    self._state["cancelled"] += 1
            return True

    def _set(self, pid: str, **fields: Any) -> None:
        with self._lock:
            row = self._state["plugins"].setdefault(pid, {})
            row.update(fields)
            self._state["done"] = sum(
                1 for p in self._state["plugins"].values()
                if p.get("status") in ("ok", "failed", "skipped", "cancelled"))

    def _run(self, active: list[str]) -> None:
        failed = 0
        cancelled = 0
        try:
            for pid in active:
                with self._lock:
                    if self._state["cancel_requested"]:
                        row = self._state["plugins"].get(pid) or {}
                        if row.get("status") == "queued":
                            row["status"] = "cancelled"
                            self._state["cancelled"] += 1
                        cancelled += 1
                        continue
                    if (self._state["plugins"].get(pid) or {}).get("status") == "cancelled":
                        cancelled += 1
                        continue
                self._set(pid, status="running")
                run_id = self.store.start_following_run(pid, ACCOUNTS_FEED)
                started = time.time()
                try:
                    accounts = self._load(pid)
                    stored = self.store.upsert_following_accounts(pid, accounts, complete=True)
                    self.store.finish_following_run(run_id, True, stored, 0)
                    self._set(pid, status="ok", count=stored, new_count=0,
                              ms=int((time.time() - started) * 1000), error="")
                    with self._lock:
                        self._state["accounts"] += stored
                except Exception as exc:
                    failed += 1
                    message = f"{type(exc).__name__}: {exc}"[:300]
                    self.store.finish_following_run(run_id, False, 0, 0, message)
                    self._set(pid, status="failed", error=message,
                              ms=int((time.time() - started) * 1000))
        finally:
            with self._lock:
                state = self._state
                for row in state["plugins"].values():
                    if row.get("status") == "queued":
                        row["status"] = "cancelled"
                        state["cancelled"] += 1
                state["done"] = sum(1 for p in state["plugins"].values()
                                    if p.get("status") in ("ok", "failed", "skipped", "cancelled"))
                state["running"] = False
                state["finished_at"] = int(time.time())
                state["cancel_requested"] = False
                if state["cancelled"] and not failed:
                    state["phase"] = "cancelled"
                elif failed and failed == len(state["plugins"]):
                    state["phase"] = "failed"
                    state["error"] = "这一轮没同步到关注名单"
                elif failed:
                    state["phase"] = "partial"
                    state["error"] = f"{failed} 个平台没同步成功"
                else:
                    state["phase"] = "done"

    def _load(self, pid: str) -> list[dict[str, Any]]:
        if getattr(self.host, "demo", False):
            raise RuntimeError("演示模式没有关注名单样例")
        accounts: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(20):
            page = self.host.following_accounts(pid, cursor=cursor, limit=50)
            accounts.extend(page.get("items") or [])
            cursor = page.get("next")
            if not cursor or len(accounts) >= ACCOUNTS_MAX:
                break
        return accounts[:ACCOUNTS_MAX]
