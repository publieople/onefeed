"""运行时设置（一份 JSON，改完立即生效）。

设置分两类，前端要如实标出来：
- 立即生效：每轮条数、评论每页条数、registry 地址、插件目录（会重新发现插件）、自动更新
- 只影响下一次启动 / 只影响前端默认值：默认排序（前端读一次）、保留天数（每轮采集后 prune）

优先级：环境变量（ONEFEED_REGISTRY / ONEFEED_PLUGINS_DIR）> settings.json > 默认值。
环境变量是给部署与测试用的，不会写回磁盘。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from plugin_runtime.paths import state_root

DEFAULT_REGISTRY = "https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/registry.json"

DEFAULTS: dict[str, Any] = {
    "plugins_dir": "",
    "registry_url": "",
    "per_plugin_limit": 12,
    "comments_limit": 20,
    "default_sort": "freshness",
    "prune_days": 14,
    # 自动更新：每轮采集前问一次 registry，有新版就静默升级。
    # 默认关：现场演示时远端悄悄改插件不是好事；要开就是一键。
    "auto_update": False,
    # AI 助手：base_url / model 可换任何 OpenAI 兼容网关；key 只进不出（GET /settings 会脱敏）。
    "ai_base_url": "https://api.deepseek.com/v1",
    "ai_model": "deepseek-chat",
    "ai_api_key": "",
}

ENV_KEYS = {"registry_url": "ONEFEED_REGISTRY", "plugins_dir": "ONEFEED_PLUGINS_DIR"}
SECRET_KEYS = ("ai_api_key",)
SORTS = ("freshness", "engagement")


def settings_file() -> Path:
    return state_root() / "settings.json"


def load() -> dict[str, Any]:
    data = dict(DEFAULTS)
    path = settings_file()
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}
        if isinstance(stored, dict):
            for key in DEFAULTS:
                if key in stored:
                    data[key] = stored[key]
    for key, env in ENV_KEYS.items():
        value = os.environ.get(env)
        if value:
            data[key] = value
    return data


def registry_url() -> str:
    return str(load().get("registry_url") or DEFAULT_REGISTRY)


def resolve_plugins_dir(raw: str) -> Path:
    """空字符串 = 用宿主默认查找顺序；路径不存在就是配置错误，别静默回退。"""
    from plugin_runtime.host import default_plugins_dir
    if not raw:
        return default_plugins_dir()
    return Path(os.path.expanduser(str(raw)))


def validate(patch: dict[str, Any]) -> dict[str, Any]:
    """只校验传进来的字段；返回归一化后的 patch。非法就抛 ValueError（带人话）。"""
    if not isinstance(patch, dict):
        raise ValueError("设置必须是一个 JSON 对象")
    out: dict[str, Any] = {}
    unknown = [k for k in patch if k not in DEFAULTS]
    if unknown:
        raise ValueError(f"未知设置项：{unknown}（可选 {sorted(DEFAULTS)}）")

    if "plugins_dir" in patch:
        raw = str(patch["plugins_dir"] or "").strip()
        if raw:
            path = Path(os.path.expanduser(raw))
            if not path.is_dir():
                raise ValueError(f"插件目录不存在：{raw}")
        out["plugins_dir"] = raw

    if "registry_url" in patch:
        raw = str(patch["registry_url"] or "").strip()
        if raw and not raw.startswith(("http://", "https://")):
            raise ValueError("registry 地址必须是 http(s) 链接")
        out["registry_url"] = raw

    for key, low, high in (("per_plugin_limit", 1, 50), ("comments_limit", 1, 50),
                           ("prune_days", 1, 365)):
        if key not in patch:
            continue
        try:
            value = int(patch[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} 必须是整数") from None
        if not (low <= value <= high):
            raise ValueError(f"{key} 必须在 {low}–{high} 之间")
        out[key] = value

    if "auto_update" in patch:
        value = patch["auto_update"]
        if not isinstance(value, bool):
            raise ValueError("auto_update 必须是 true / false")
        out["auto_update"] = value

    if "default_sort" in patch:
        value = str(patch["default_sort"] or "")
        if value not in SORTS:
            raise ValueError(f"default_sort 只能是 {', '.join(SORTS)}")
        out["default_sort"] = value

    if "ai_base_url" in patch:
        raw = str(patch["ai_base_url"] or "").strip().rstrip("/")
        if raw and not raw.startswith(("http://", "https://")):
            raise ValueError("ai_base_url 必须是 http(s) 链接（OpenAI 兼容网关，通常以 /v1 结尾）")
        out["ai_base_url"] = raw or DEFAULTS["ai_base_url"]

    if "ai_model" in patch:
        value = str(patch["ai_model"] or "").strip()
        out["ai_model"] = value or DEFAULTS["ai_model"]

    if "ai_api_key" in patch:
        out["ai_api_key"] = str(patch["ai_api_key"] or "").strip()

    return out


def save(patch: dict[str, Any]) -> dict[str, Any]:
    normalized = validate(patch)
    current = load()
    # 环境变量覆盖的值不落盘（否则用户以为改了、实际还被 env 压着）
    stored = {k: v for k, v in current.items() if k not in ENV_KEYS or not os.environ.get(ENV_KEYS[k])}
    stored.update(normalized)
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=1), encoding="utf-8")
    return load()