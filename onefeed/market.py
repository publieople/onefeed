"""插件市场（003 T38–T41）。

registry 拉取带一小时缓存与 ETag 式降级；安装走「下载 → 目录级 sha256 校验 → 原子改名」。
装不上的时候把原因原样抛给前端，不假装成功。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from plugin_runtime.host import default_plugins_dir
from plugin_runtime.paths import state_root

FALLBACK_REGISTRY = "https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/registry.json"
# 老的常量名保留：外部脚本 / 测试还在 import 它
REGISTRY_URL = os.environ.get("ONEFEED_REGISTRY", FALLBACK_REGISTRY)
CACHE_TTL = 3600
UA = "OneFeed/0.3 (+local demo)"


def registry_url() -> str:
    """设置页可以随时改地址；环境变量优先，其次 settings.json，最后内置默认。"""
    try:
        from . import settings as settings_mod
        return settings_mod.registry_url()
    except Exception:
        return os.environ.get("ONEFEED_REGISTRY") or FALLBACK_REGISTRY


def _cache_dir() -> Path:
    path = state_root() / "market"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_file(url: str) -> Path:
    """缓存按地址分开存：换了 registry 就不会读到上一个源的旧目录。"""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return _cache_dir() / f"registry-{digest}.json"


def _http_bytes(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def registry(force: bool = False) -> dict[str, Any]:
    url = registry_url()
    cache = _cache_file(url)
    if not force and cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < CACHE_TTL:
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                data["from_cache"] = True
                return data
            except json.JSONDecodeError:
                pass
    try:
        data = json.loads(_http_bytes(url).decode("utf-8"))
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        data["from_cache"] = False
        return data
    except Exception as exc:
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            data["from_cache"] = True
            data["degraded"] = f"{type(exc).__name__}: {exc}"[:200]
            return data
        return {"schemaVersion": 1, "plugins": [], "degraded":
                f"拿不到 registry，也没有缓存：{type(exc).__name__}: {exc}"[:200]}


def merged(store, force: bool = False) -> dict[str, Any]:
    url = registry_url()
    data = registry(force)
    installed = {p["id"]: p for p in store.list_plugins()}
    entries = []
    for entry in data.get("plugins", []):
        pid = entry.get("id")
        current = installed.pop(pid, None)
        entries.append({
            **entry,
            "installed": bool(current),
            "installed_version": (current or {}).get("version", ""),
            "enabled": bool((current or {}).get("enabled", 1)) if current else False,
            "latest_version": str(entry.get("version") or ""),
            # 只有真的比已装版本新才算可更新：registry 回退版本时不该提示"更新"
            "update_available": bool(current) and cmp_version(
                (current or {}).get("version", ""), entry.get("version", "")) < 0,
        })
    for pid, row in installed.items():  # 本地装的、registry 里没有的
        entries.append({"id": pid, "name": pid, "version": row.get("version", ""),
                        "description": "本地安装的插件", "installed": True,
                        "installed_version": row.get("version", ""),
                        "enabled": bool(row.get("enabled", 1)), "update_available": False,
                        "capabilities": [], "kinds": [], "feeds": []})
    return {"entries": entries, "degraded": data.get("degraded", ""),
            "from_cache": data.get("from_cache", False), "url": url}


# ---------------------------------------------------------------- 安装

def _lf(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def dir_hash(root: Path) -> str:
    """与 onefeed-plugins/scripts/build_registry.py 同算法。"""
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(root).as_posix())
    outer = hashlib.sha256()
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        inner = hashlib.sha256(_lf(path)).hexdigest().encode("ascii")  # 与 build_registry.py 一致：喂十六进制摘要
        outer.update(rel + b"\0" + inner + b"\n")
    return outer.hexdigest()


def _github_files(plugin_id: str) -> list[tuple[str, str]]:
    url = (f"https://api.github.com/repos/publieople/onefeed-plugins/contents/"
           f"plugins/{plugin_id}?ref=main")
    payload = json.loads(_http_bytes(url).decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError(f"仓库里没有插件 {plugin_id}")
    out = []
    for node in payload:
        if node.get("type") == "file" and node.get("download_url"):
            out.append((node["name"], node["download_url"]))
    return out


JSDELIVR_FLAT = ("https://data.jsdelivr.com/v1/package/gh/publieople/"
                 "onefeed-plugins@main/flat")
JSDELIVR_RAW = "https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/"


def _jsdelivr_files(plugin_id: str) -> list[tuple[str, str]]:
    """GitHub API 有每小时 60 次的匿名限额，超了就改走 jsDelivr 的静态镜像。"""
    data = json.loads(_http_bytes(JSDELIVR_FLAT).decode("utf-8"))
    prefix = "/plugins/" + plugin_id + "/"
    out: list[tuple[str, str]] = []
    for node in data.get("files", []):
        name = str(node.get("name", ""))
        if name.startswith(prefix):
            out.append((name[len(prefix):], JSDELIVR_RAW + name.lstrip("/")))
    return out


def _remote_files(plugin_id: str) -> list[tuple[str, str]]:
    try:
        files = _github_files(plugin_id)
        if files:
            return files
    except Exception:
        pass  # 限额、网络、404 都往下走 CDN
    files = _jsdelivr_files(plugin_id)
    if not files:
        raise RuntimeError(f"{plugin_id} 在 GitHub 与 jsDelivr 上都找不到文件")
    return files


def plugins_root() -> Path:
    """安装目标目录跟随设置；设置里留空就用宿主默认查找顺序。"""
    try:
        from . import settings as settings_mod
        return settings_mod.resolve_plugins_dir(str(settings_mod.load().get("plugins_dir") or ""))
    except Exception:
        return Path(default_plugins_dir())


def install(store, plugin_id: str) -> dict[str, Any]:
    entry = next((e for e in merged(store)["entries"] if e.get("id") == plugin_id), None)
    if entry is None:
        raise RuntimeError(f"registry 里没有 {plugin_id}")
    target_root = plugins_root()
    target = target_root / plugin_id
    expected = str(entry.get("sha256") or "")
    # 更新不能把用户关掉的插件又打开：先记住现有 enabled，写库时带回去
    previous = next((p for p in store.list_plugins() if p["id"] == plugin_id), None)
    keep_enabled = bool((previous or {}).get("enabled", 1))

    # 下载缓存按「插件 + 期望 sha」分开存：只按 id 存的话，
    # registry 一升级就会命中上一版的旧包，sha 永远对不上、更新永久失败。
    cache_root = _cache_dir() / "plugins"
    cache_key = f"{plugin_id}-{(expected or 'nohash')[:12]}"
    cached = cache_root / cache_key
    tmp = Path(tempfile.mkdtemp(prefix=f"of-{plugin_id}-", dir=str(target_root.parent)))
    try:
        if (cached / "plugin.json").exists():
            shutil.copytree(cached, tmp / "pkg")
        else:
            files = _remote_files(plugin_id)
            for name, url in files:
                (tmp / "pkg" / name).parent.mkdir(parents=True, exist_ok=True)
                (tmp / "pkg" / name).write_bytes(_http_bytes(url))
        pkg = tmp / "pkg"
        if not (pkg / "plugin.json").exists():
            raise RuntimeError("下载到的内容里没有 plugin.json")
        actual = dir_hash(pkg)
        if expected and actual != expected:
            raise RuntimeError(f"sha256 不符（期望 {expected[:12]}…，实际 {actual[:12]}…），已拒绝安装")
        if target.exists():
            shutil.rmtree(target)
        pkg.rename(target)
        cache_root.mkdir(parents=True, exist_ok=True)
        for old in cache_root.glob(f"{plugin_id}-*"):  # 旧版本的缓存没用了
            if old != cached:
                shutil.rmtree(old, ignore_errors=True)
        if cached.exists():
            shutil.rmtree(cached)
        shutil.copytree(target, cached)
        manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        store.upsert_plugin(plugin_id, str(manifest.get("version", entry.get("version", ""))),
                            actual, source="registry", enabled=keep_enabled)
        return {"ok": True, "id": plugin_id, "version": manifest.get("version"), "sha256": actual}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 版本与更新

def version_key(value: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(value or ""))
    return tuple(int(n) for n in nums) or (0,)


def cmp_version(a: str, b: str) -> int:
    """语义化版本比较：a<b 返回 -1，相等 0，a>b 返回 1。缺失段按 0 补齐。"""
    ka, kb = version_key(a), version_key(b)
    width = max(len(ka), len(kb))
    ka += (0,) * (width - len(ka))
    kb += (0,) * (width - len(kb))
    return (ka > kb) - (ka < kb)


def update(store, plugin_id: str) -> dict[str, Any]:
    """把一个已装插件升到 registry 上的版本。返回 from / to，方便前端说清升了什么。"""
    previous = next((p for p in store.list_plugins() if p["id"] == plugin_id), None)
    if previous is None:
        raise RuntimeError(f"{plugin_id} 还没装，先安装再更新")
    entry = next((e for e in merged(store)["entries"] if e.get("id") == plugin_id), None)
    if entry is None:
        raise RuntimeError(f"registry 里没有 {plugin_id}")
    latest = str(entry.get("version") or "")
    if cmp_version(previous.get("version", ""), latest) >= 0:
        return {"ok": True, "id": plugin_id, "changed": False,
                "from": previous.get("version", ""), "to": previous.get("version", "")}
    install(store, plugin_id)
    after = next((p for p in store.list_plugins() if p["id"] == plugin_id), None)
    return {"ok": True, "id": plugin_id, "changed": True,
            "from": previous.get("version", ""), "to": (after or {}).get("version", latest)}


def update_all(store) -> dict[str, Any]:
    """把所有「可更新」的插件升一轮。单个失败不影响其它，失败原因原样带回。"""
    data = merged(store)
    todo = [e for e in data.get("entries", [])
            if e.get("installed") and e.get("update_available")]
    updated: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for entry in todo:
        pid = str(entry.get("id") or "")
        try:
            updated.append(update(store, pid))
        except Exception as exc:
            failed.append({"id": pid, "error": f"{type(exc).__name__}: {exc}"[:200]})
    return {"ok": not failed, "checked": len(data.get("entries", [])),
            "pending": len(todo), "updated": updated, "failed": failed}


def pending_updates(store) -> list[dict[str, Any]]:
    """给设置页 / 状态接口用：只回可更新的那几条，不碰网络（用缓存）。"""
    return [{"id": e.get("id"), "from": e.get("installed_version", ""),
             "to": e.get("version", "")}
            for e in merged(store).get("entries", [])
            if e.get("installed") and e.get("update_available")]


def uninstall(store, plugin_id: str) -> dict[str, Any]:
    """卸载插件：目录是主，库只是索引。

    目录已经不在时也把库里那行清掉，而不是报「没有安装」。之前正是这一步
    让「目录被手工删掉 → 卸载被拒 → 市场页永远显示已安装」成了死锁。
    """
    target = plugins_root() / plugin_id
    removed = False
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            target.unlink()
        else:
            shutil.rmtree(target)
        removed = True
    store.delete_plugin(plugin_id)
    return {"ok": True, "id": plugin_id, "removed": removed}
