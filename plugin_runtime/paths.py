"""运行时目录：插件状态、浏览器档案、缓存。

为什么不是直接写 `~/.onefeed`：本机实测 workspace 里的 venv python 无法写
用户目录（C:\\Users\\Publieople 下全被拒），换个解释器又正常。与其赌环境，
不如按"能写就用，不能写就退回仓库内"处理，并允许 ONEFEED_HOME 显式覆盖。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FALLBACK = ROOT / ".onefeed"
_cache: Path | None = None


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def state_root() -> Path:
    """状态根目录：ONEFEED_HOME > 可写的 ~/.onefeed > 仓库内 .onefeed（已 gitignore）。"""
    global _cache
    if _cache is not None:
        return _cache
    env = os.environ.get("ONEFEED_HOME")
    if env:
        _cache = Path(env).expanduser()
    else:
        home = Path.home() / ".onefeed"
        _cache = home if _writable(home) else _FALLBACK
    _cache.mkdir(parents=True, exist_ok=True)
    return _cache


def plugin_dir(plugin_id: str) -> Path:
    target = state_root() / "plugins" / plugin_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def browser_profile(plugin_id: str) -> Path:
    target = state_root() / "browser" / plugin_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_temp_env() -> Path:
    """把 TMP/TEMP/TMPDIR 指到可写目录；playwright 的 node driver 依赖它们。"""
    target = scratch_dir()
    for key in ("TMP", "TEMP", "TMPDIR"):
        os.environ[key] = str(target)
    return target


def scratch_dir() -> Path:
    target = state_root() / "tmp"
    target.mkdir(parents=True, exist_ok=True)
    return target
