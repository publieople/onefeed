"""宿主侧调度：发现插件、起 worker 子进程、把 RawItem 归一化成 Item。

宿主不 import 插件、不 eval 插件代码——插件代码只活在自己那个子进程里。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from models import Item, clamp

from .capabilities import clean_env
from .manifest import HOST_VERSION, Manifest, ManifestError, load_manifest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUTS = {"pull": 92.0, "comments": 92.0, "detail": 92.0, "auth": 60.0, "init": 30.0}


def default_plugins_dir() -> Path:
    """插件目录查找顺序：环境变量 → 同级 onefeed-plugins 仓库 → 仓库内 plugins/。"""
    env = os.environ.get("ONEFEED_PLUGINS_DIR")
    if env:
        return Path(os.path.expanduser(env))
    sibling = ROOT.parent / "onefeed-plugins" / "plugins"
    if sibling.is_dir():
        return sibling
    return ROOT / "plugins"


def to_item(plugin_id: str, raw: dict[str, Any], fetched_at: int | None = None) -> Item:
    """RawItem（插件交的）→ Item（宿主用的）。缺字段按规范降级，不编造。"""
    if not isinstance(raw, dict):
        raise ValueError(f"item 必须是对象，收到 {type(raw).__name__}")
    native_id = raw.get("native_id")
    if not native_id:
        raise ValueError("item 缺少 native_id")
    stats = raw.get("stats") or {}
    author = raw.get("author") or {}
    if not isinstance(author, dict):
        author = {"name": str(author)}

    title = str(raw.get("title") or "").strip()
    text = str(raw.get("text") or "")
    if not title:
        title = text.strip().splitlines()[0][:60] if text.strip() else "（无标题）"

    return Item(
        id=f"{plugin_id}:{native_id}",
        platform=plugin_id,
        raw_id=str(native_id),
        title=title[:200],
        kind=str(raw.get("kind") or "article"),
        text=text[:2000],
        author=str(author.get("name") or ""),
        author_id=str(author.get("id") or ""),
        author_avatar=str(author.get("avatar") or ""),
        cover=str(raw.get("cover") or ""),
        images=[str(u) for u in (raw.get("images") or [])][:9],
        url=str(raw.get("url") or ""),
        published_at=clamp(raw.get("published_at") or 0),
        duration=clamp(raw.get("duration") or 0),
        like=clamp(stats.get("like")), comment=clamp(stats.get("comment")),
        share=clamp(stats.get("share")), view=clamp(stats.get("view")),
        tags=[str(t) for t in (raw.get("tags") or [])][:6],
        fetched_at=fetched_at or int(time.time()),
        extra=raw.get("extra") if isinstance(raw.get("extra"), dict) else {},
    )


class PluginHost:
    def __init__(self, plugins_dir: Path | str | None = None, settings: dict[str, dict] | None = None,
                 demo: bool | None = None, host_version: str = HOST_VERSION):
        self.plugins_dir = Path(plugins_dir) if plugins_dir else default_plugins_dir()
        self.settings = settings or {}
        self.demo = demo if demo is not None else os.environ.get("ONEFEED_DEMO") == "1"
        self.host_version = host_version
        self._manifests: dict[str, Manifest] = {}
        self.errors: list[str] = []

    # ------------------------------------------------------------ 发现
    def discover(self) -> list[Manifest]:
        self._manifests.clear()
        self.errors.clear()
        if not self.plugins_dir.is_dir():
            raise ManifestError(f"插件目录不存在: {self.plugins_dir}")
        found: list[Manifest] = []
        for child in sorted(self.plugins_dir.iterdir()):
            if not child.is_dir() or not (child / "plugin.json").is_file():
                continue
            try:
                m = load_manifest(child, host_version=self.host_version)
            except ManifestError as exc:
                self.errors.append(str(exc))
                continue
            if m.id in self._manifests:
                self.errors.append(f"插件 id 重复：{m.id}（{child}）")
                continue
            self._manifests[m.id] = m
            found.append(m)
        return found

    def get(self, plugin_id: str) -> Manifest:
        if not self._manifests:
            self.discover()
        if plugin_id not in self._manifests:
            raise KeyError(f"未找到插件 {plugin_id}（已发现 {sorted(self._manifests)}）")
        return self._manifests[plugin_id]

    # ------------------------------------------------------------ 调用
    def run(self, plugin_id: str, method: str, args: dict | None = None,
            timeout: float | None = None) -> dict[str, Any]:
        manifest = self.get(plugin_id)
        if timeout is None:
            timeout = DEFAULT_TIMEOUTS.get(method, 30.0)
            if "browser" in manifest.capabilities:
                timeout = max(timeout, 92.0)

        cmd = [sys.executable, "-m", "plugin_runtime.worker", str(manifest.path),
               method, json.dumps(args or {}, ensure_ascii=False)]
        env = clean_env()
        env["ONEFEED_SETTINGS"] = json.dumps(self.settings.get(plugin_id) or {}, ensure_ascii=False)
        # 让 worker 在宿主强杀前自己收尾：留 6s 给进程退出与结果写出
        env["ONEFEED_DEADLINE_SEC"] = f"{max(5.0, timeout - 6.0):.0f}"
        if self.demo:
            env["ONEFEED_DEMO"] = "1"

        started = time.time()
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, text=True, encoding="utf-8", errors="replace")
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid)
            stdout, stderr = proc.communicate()
            timed_out = True

        elapsed = round(time.time() - started, 2)
        if timed_out:
            return {"ok": False, "plugin": plugin_id, "elapsed": elapsed,
                    "error": f"timeout after {timeout:.0f}s（子进程已强杀）"}

        line = ""
        for candidate in reversed((stdout or "").strip().splitlines()):
            if candidate.strip().startswith("{"):
                line = candidate.strip()
                break
        if not line:
            return {"ok": False, "plugin": plugin_id, "elapsed": elapsed,
                    "error": (stderr or "worker 无输出").strip()[-800:]}
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return {"ok": False, "plugin": plugin_id, "elapsed": elapsed,
                    "error": f"worker 输出不是 JSON: {line[:300]}"}

        if payload.get("error"):
            return {"ok": False, "plugin": plugin_id, "elapsed": elapsed,
                    "error": str(payload["error"])[:800]}
        return {"ok": True, "plugin": plugin_id, "elapsed": elapsed,
                "value": payload.get("value"), "stderr": (stderr or "")[-2000:]}

    def pull(self, plugin_id: str, feed_id: str | None = None, limit: int = 20,
             cursor: str | None = None) -> list[Item]:
        manifest = self.get(plugin_id)
        feed = feed_id or manifest.default_feed
        if manifest.feeds and feed not in manifest.feed_ids():
            raise ValueError(f"{plugin_id} 没有名为 {feed} 的流（有 {manifest.feed_ids()}）")
        out = self.run(plugin_id, "pull", {"feedId": feed, "limit": limit, "cursor": cursor})
        if not out["ok"]:
            raise RuntimeError(f"[{plugin_id}] {out['error']}")
        value = out["value"] or {}
        items = value.get("items") if isinstance(value, dict) else None
        if not isinstance(items, list):
            raise RuntimeError(f"[{plugin_id}] pull 必须返回 {{items: [], next: null}}")

        now = int(time.time())
        result: list[Item] = []
        for raw in items:
            try:
                result.append(to_item(plugin_id, raw, fetched_at=now))
            except ValueError as exc:
                print(f"[{plugin_id}] 跳过无效 item: {exc}", file=sys.stderr)
        result.sort(key=lambda x: x.published_at, reverse=True)
        return result[:limit]

    def comments(self, plugin_id: str, item: Item, limit: int = 20) -> list[dict[str, Any]]:
        out = self.run(plugin_id, "comments", {"item": item.to_dict(), "limit": limit})
        if not out["ok"]:
            raise RuntimeError(f"[{plugin_id}] {out['error']}")
        value = out["value"] or {}
        return list((value.get("items") if isinstance(value, dict) else []) or [])

    def auth(self, plugin_id: str) -> dict[str, Any]:
        manifest = self.get(plugin_id)
        if not any(f.requires_auth for f in manifest.feeds):
            return {"state": "not_required"}
        out = self.run(plugin_id, "auth", {})
        return out["value"] if out["ok"] else {"state": "error", "error": out["error"]}

    def pull_many(self, plugin_ids: Iterable[str] | None = None, limit: int = 20) -> tuple[list[Item], list[dict]]:
        """并发不了（每个插件一个进程），但串行拉一轮也就几秒。"""
        ids = list(plugin_ids) if plugin_ids else [m.id for m in self.discover()]
        items: list[Item] = []
        failures: list[dict] = []
        for pid in ids:
            try:
                items.extend(self.pull(pid, limit=limit))
            except Exception as exc:
                failures.append({"plugin": pid, "error": f"{type(exc).__name__}: {exc}"})
        items.sort(key=lambda x: x.published_at, reverse=True)
        return items, failures


def _kill_tree(pid: int) -> None:
    """Windows 上 worker 会 fork 出 chrome；只杀 worker 会留孤儿。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(pid), 9)
        except OSError:
            pass
