"""插件市场（003 T38–T41）。

registry 拉取带一小时缓存与 ETag 式降级；安装走「下载 → 目录级 sha256 校验 → 原子改名」。
装不上的时候把原因原样抛给前端，不假装成功。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from plugin_runtime.host import default_plugins_dir
from plugin_runtime.paths import state_root

REGISTRY_URL = os.environ.get(
    "ONEFEED_REGISTRY",
    "https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/registry.json")
CACHE_TTL = 3600
UA = "OneFeed/0.3 (+local demo)"


def _cache_dir() -> Path:
    path = state_root() / "market"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _http_bytes(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def registry(force: bool = False) -> dict[str, Any]:
    cache = _cache_dir() / "registry.json"
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
        data = json.loads(_http_bytes(REGISTRY_URL).decode("utf-8"))
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
            "update_available": bool(current) and current.get("version") != entry.get("version"),
        })
    for pid, row in installed.items():  # 本地装的、registry 里没有的
        entries.append({"id": pid, "name": pid, "version": row.get("version", ""),
                        "description": "本地安装的插件", "installed": True,
                        "installed_version": row.get("version", ""),
                        "enabled": bool(row.get("enabled", 1)), "update_available": False,
                        "capabilities": [], "kinds": [], "feeds": []})
    return {"entries": entries, "degraded": data.get("degraded", ""),
            "from_cache": data.get("from_cache", False), "url": REGISTRY_URL}


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


def install(store, plugin_id: str) -> dict[str, Any]:
    entry = next((e for e in merged(store)["entries"] if e.get("id") == plugin_id), None)
    if entry is None:
        raise RuntimeError(f"registry 里没有 {plugin_id}")
    target_root = Path(default_plugins_dir())
    target = target_root / plugin_id
    expected = str(entry.get("sha256") or "")

    cached = _cache_dir() / "plugins" / plugin_id
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
        cached.parent.mkdir(parents=True, exist_ok=True)
        if cached.exists():
            shutil.rmtree(cached)
        shutil.copytree(target, cached)
        manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        store.upsert_plugin(plugin_id, str(manifest.get("version", entry.get("version", ""))),
                            actual, source="registry")
        return {"ok": True, "id": plugin_id, "version": manifest.get("version"), "sha256": actual}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def uninstall(store, plugin_id: str) -> dict[str, Any]:
    target = Path(default_plugins_dir()) / plugin_id
    if not target.exists():
        raise RuntimeError(f"{plugin_id} 没有安装")
    shutil.rmtree(target)
    store.delete_plugin(plugin_id)
    return {"ok": True, "id": plugin_id}
