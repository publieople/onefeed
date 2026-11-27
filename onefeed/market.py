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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from plugin_runtime.host import default_plugins_dir
from plugin_runtime.manifest import ID_RE
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


# 本机回环允许 http：本地开发、测试 registry 用；其余地址必须是 https。
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def _check_registry_url(url: str) -> str:
    """registry 地址的传输协议校验（OF-36）：只收 https，本机回环例外。

    插件包和 registry 清单都从这个地址取。明文 http 下同网段的人可以把
    registry 和包一起换掉，sha256 也是同一个源头给的，校验等于没有。
    """
    text = str(url or "").strip()
    parts = urllib.parse.urlsplit(text)
    if parts.scheme == "https":
        return text
    if parts.scheme == "http" and (parts.hostname or "").lower() in _LOOPBACK_HOSTS:
        return text
    raise RuntimeError(f"registry 地址必须是 https：{text or '（空）'}")


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
    try:
        # OF-36：明文 registry 连缓存都不认（缓存可能来自被降级的地址）。
        _check_registry_url(url)
    except RuntimeError as exc:
        if cache.exists():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                data["from_cache"] = True
                data["degraded"] = str(exc)[:200]
                return data
            except json.JSONDecodeError:
                pass
        return {"schemaVersion": 1, "plugins": [], "degraded": str(exc)[:200]}
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


class InvalidPluginId(ValueError):
    """插件 id 不能用做目录名（OF-04）："." / ".." / 带路径分隔符的 id 一律拒绝。"""


def validate_plugin_id(plugin_id: str) -> str:
    """把 URL 路径里的 plugin_id 校验成能安全当目录名用的 id。

    和清单 id 用同一套规则（plugin_runtime.manifest.ID_RE）：小写字母开头、
    只用小写字母/数字/连字符、2–32 位。字符集本身就把 "."、".."、"a/b"、
    "a\\b" 挡在外面——以前 DELETE /api/plugins/%2E 会把插件根自己当成插件
    目录，rename 走整个根。
    """
    pid = str(plugin_id or "")
    if not ID_RE.match(pid):
        raise InvalidPluginId(
            f"非法的插件 id：{pid!r}（小写字母开头，只用小写字母、数字、连字符，2–32 位）")
    return pid


def plugin_target(root: Path, plugin_id: str) -> Path:
    """插件目录 = 插件根 / id，且必须是根的下一层。

    先校验 id，再确认拼出来的路径父目录就是插件根（不解析目标本身：开发时
    用软链把插件目录指到仓库里是既有用法，删除/改名走的是链接本身）。
    """
    pid = validate_plugin_id(plugin_id)
    root = Path(root)
    target = root / pid
    if target.name != pid or target.parent.resolve() != root.resolve():
        raise InvalidPluginId(f"插件目录不在插件根内：{target}")
    return target


class InstallRollbackError(RuntimeError):
    """换入失败、回滚也失败时抛出：旧目录仍在备份位置，人工还能救回来。"""


def _path_exists(path: Path) -> bool:
    # Path.exists() 对断掉的符号链接返回 False；插件目录出过事，这里不省这一步。
    return path.is_symlink() or path.exists()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _move_path(src: Path, dst: Path) -> None:
    """单独包一层，测试可以只让某一次改名失败，不用真的锁住目录。"""
    src.rename(dst)


def _work_dir(target_root: Path, plugin_id: str) -> Path:
    # 和插件目录同级，不在插件根里面：sync_installed / host.discover 不会把
    # 半成品或备份当成插件扫进去。同一卷内改名才是原子的。
    return Path(tempfile.mkdtemp(prefix=f".of-{plugin_id}-", dir=str(target_root.parent)))


def _write_meta(work: Path, payload: dict[str, Any]) -> None:
    """给崩溃恢复留一张小纸条：这是哪个插件、目标在哪、做到哪一步。"""
    (work / "meta.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _keep_work(work: Path, plugin_id: str, target: Path, action: str) -> None:
    """回滚都失败时，把现场标成 preserve，启动恢复不要误删备份。"""
    try:
        _write_meta(work, {"plugin_id": plugin_id, "target": str(target),
                           "action": action, "preserve": True})
    except OSError:
        pass


def recover_installs(store, root: Path | None = None) -> int:
    """启动时处理上次进程被强杀留下的工作目录。

    - 旧目录已经移走、新目录还没换入：把备份移回去（卸载时如果库记录
      已经删掉，说明卸载其实完成了，直接清掉备份）。
    - 新目录已经换入、库还没写：按磁盘上的 manifest 把库补成新版本。
    - 回滚失败的 preserve 现场原地保留，等人来看，不自动删。
    """
    root = Path(root or default_plugins_dir())
    if not root.parent.is_dir():
        return 0
    recovered = 0
    for work in sorted(root.parent.glob(".of-*")):
        if not work.is_dir():
            continue
        try:
            meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # 不是我们的工作目录，不动
        if meta.get("preserve"):
            continue
        plugin_id = str(meta.get("plugin_id") or "")
        try:
            target = Path(str(meta.get("target") or ""))
        except (TypeError, ValueError):
            continue
        if not plugin_id or target.parent.resolve() != root.resolve():
            continue
        action = str(meta.get("action") or "install")
        backup = work / "previous"
        row = next((p for p in store.list_plugins() if p["id"] == plugin_id), None)
        if not _path_exists(target) and _path_exists(backup):
            if action == "uninstall" and row is None:
                pass  # 卸载已经写库成功，备份可以清
            else:
                try:
                    _move_path(backup, target)
                    recovered += 1
                except OSError:
                    continue  # 还是被占用：留着，下次启动再试
        if _path_exists(target) and action != "uninstall":
            try:
                manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
                actual = dir_hash(target)
                store.upsert_plugin(
                    plugin_id, str(manifest.get("version", "")), actual,
                    source="registry", enabled=bool((row or {}).get("enabled", 1)))
            except (OSError, json.JSONDecodeError):
                pass
        shutil.rmtree(work, ignore_errors=True)
    return recovered


def _rollback(target: Path, backup: Path, had_previous: bool) -> None:
    problems: list[str] = []
    if _path_exists(target):
        try:
            _remove_path(target)
        except OSError as exc:
            problems.append(f"清不掉半截新目录：{type(exc).__name__}: {exc}")
    if had_previous:
        if not _path_exists(backup):
            problems.append(f"备份不在了：{backup}")
        else:
            try:
                _move_path(backup, target)
            except OSError as exc:
                problems.append(f"备份移不回去：{type(exc).__name__}: {exc}")
    if problems:
        raise InstallRollbackError("；".join(problems))


def _refresh_cache(plugin_id: str, target: Path, cached: Path, cache_root: Path) -> None:
    """把刚装好的目录复制进下载缓存，供下次离线安装。

    缓存只是加速，不是事实来源：复制失败不回滚已经装好的插件，只把警告
    带回去。先复制到临时目录再换名，避免下次命中一个只写了一半的缓存。
    """
    cache_root.mkdir(parents=True, exist_ok=True)
    tmp = cache_root / f".{cached.name}.tmp-{os.getpid()}-{time.time_ns()}"
    try:
        shutil.copytree(target, tmp)
        if _path_exists(cached):
            _remove_path(cached)
        _move_path(tmp, cached)
    finally:
        if _path_exists(tmp):
            _remove_path(tmp)
    for old in cache_root.glob(f"{plugin_id}-*"):  # 旧版本的缓存没用了
        if old != cached:
            try:
                _remove_path(old)
            except OSError:
                pass


def install(store, plugin_id: str) -> dict[str, Any]:
    """安装或替换插件：先 staging 校验，再备份旧目录、原子换入，最后写库。

    顺序和 DSH 的安装器一致：可恢复状态先留好，失败按备份回滚，不把旧目录
    先删掉。之前正是 shutil.rmtree(target) 之后任何一步失败（目录被占用、
    rename 失败、缓存复制失败）都会留下空目录或半截包，库里却还是旧记录。
    """
    plugin_id = validate_plugin_id(plugin_id)
    # OF-36：即使在缓存期内，也不允许从一个明文 registry 的条目安装。
    _check_registry_url(registry_url())
    entry = next((e for e in merged(store)["entries"] if e.get("id") == plugin_id), None)
    if entry is None:
        raise RuntimeError(f"registry 里没有 {plugin_id}")
    target_root = plugins_root()
    target_root.mkdir(parents=True, exist_ok=True)
    target = plugin_target(target_root, plugin_id)
    expected = str(entry.get("sha256") or "").strip().lower()
    if not expected:
        # OF-36：以前空 sha 会让下面的校验全部变成空操作，registry 被替换就能随便换包。
        raise RuntimeError(f"registry 里的 {plugin_id} 没有 sha256，拒绝安装未经校验的包")
    # 更新不能把用户关掉的插件又打开：先记住现有 enabled，写库时带回去
    previous = next((p for p in store.list_plugins() if p["id"] == plugin_id), None)
    keep_enabled = bool((previous or {}).get("enabled", 1))

    # 下载缓存按「插件 + 期望 sha」分开存：只按 id 存的话，
    # registry 一升级就会命中上一版的旧包，sha 永远对不上、更新永久失败。
    cache_root = _cache_dir() / "plugins"
    cache_key = f"{plugin_id}-{(expected or 'nohash')[:12]}"
    cached = cache_root / cache_key
    work = _work_dir(target_root, plugin_id)
    staging = work / "new"
    backup = work / "previous"
    had_previous = _path_exists(target)
    moved_old = False
    swapped = False
    keep_work = False
    try:
        _write_meta(work, {"plugin_id": plugin_id, "target": str(target),
                           "action": "install"})
        if (cached / "plugin.json").exists():
            shutil.copytree(cached, staging)
        else:
            files = _remote_files(plugin_id)
            for name, url in files:
                (staging / name).parent.mkdir(parents=True, exist_ok=True)
                (staging / name).write_bytes(_http_bytes(url))
        if not (staging / "plugin.json").exists():
            raise RuntimeError("下载到的内容里没有 plugin.json")
        try:
            staged = json.loads((staging / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"plugin.json 读不出来：{type(exc).__name__}: {exc}") from exc
        if not isinstance(staged, dict):
            raise RuntimeError("plugin.json 不是 JSON 对象")
        staged_id = str(staged.get("id") or "")
        if staged_id != plugin_id:
            # OF-36：registry 条目的 id 必须和包里的清单一致，写错或换包都别换入。
            raise RuntimeError(
                f"下载到的插件清单 id 是 {staged_id!r}，与 registry 条目 {plugin_id!r} 不符，已拒绝安装")
        actual = dir_hash(staging)
        if actual != expected:
            raise RuntimeError(f"sha256 不符（期望 {expected[:12]}…，实际 {actual[:12]}…），已拒绝安装")

        if had_previous:
            _move_path(target, backup)
            moved_old = True
        _move_path(staging, target)
        swapped = True

        # 换入后再校验一遍，防止跨卷/占用导致只搬了一半（DSH 的 post-install check）。
        manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        actual = dir_hash(target)
        if actual != expected:
            raise RuntimeError(f"落盘后 sha256 不符（期望 {expected[:12]}…，实际 {actual[:12]}…）")
        # 数据库最后写：前面任何一步失败，旧记录和旧目录都还在。
        store.upsert_plugin(plugin_id, str(manifest.get("version", entry.get("version", ""))),
                            actual, source="registry", enabled=keep_enabled)
    except Exception as exc:
        if moved_old or swapped:
            try:
                _rollback(target, backup, moved_old)
            except Exception as rb:
                keep_work = True
                _keep_work(work, plugin_id, target, "install")
                raise InstallRollbackError(
                    f"{exc}；回滚失败：{rb}。旧目录备份在 {backup}") from exc
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
        raise
    warning = ""
    try:
        _refresh_cache(plugin_id, target, cached, cache_root)
    except Exception as exc:  # 缓存失败只降级，不影响已经装好的插件
        warning = f"缓存没更新成功：{type(exc).__name__}: {exc}"[:200]
    try:
        return {"ok": True, "id": plugin_id, "version": manifest.get("version"),
                "sha256": actual, "cache_warning": warning}
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)


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
    plugin_id = validate_plugin_id(plugin_id)
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

    目录还在时也不直接 rmtree：先改名为备份，库删成功后再删备份。库删失败
    就把目录移回去，避免出现「目录没了、库里还显示已安装」的半截状态。
    """
    plugin_id = validate_plugin_id(plugin_id)
    target_root = plugins_root()
    target = plugin_target(target_root, plugin_id)
    if not _path_exists(target):
        store.delete_plugin(plugin_id)
        return {"ok": True, "id": plugin_id, "removed": False}
    target_root.mkdir(parents=True, exist_ok=True)
    work = _work_dir(target_root, plugin_id)
    backup = work / "previous"
    keep_work = False
    try:
        _write_meta(work, {"plugin_id": plugin_id, "target": str(target),
                           "action": "uninstall"})
        _move_path(target, backup)
        try:
            store.delete_plugin(plugin_id)
        except Exception as exc:
            try:
                _move_path(backup, target)
            except Exception as rb:
                keep_work = True
                _keep_work(work, plugin_id, target, "uninstall")
                raise InstallRollbackError(
                    f"{exc}；卸载回滚失败：{rb}。插件目录备份在 {backup}") from exc
            raise
        return {"ok": True, "id": plugin_id, "removed": True}
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
