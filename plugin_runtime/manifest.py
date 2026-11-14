"""插件清单（plugin.json）：加载、校验、semver 比较。

校验目标是"给出可读报错"，不是"拦住一切"。宿主拒绝装载时，
用户应当能从报错里直接知道改哪一行。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
HOST_VERSION = "0.2.0"
CAPABILITIES = {"http", "browser", "cli"}
KINDS = {"video", "images", "article", "short", "list"}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ManifestError(ValueError):
    """清单不合法；消息面向插件作者，带上具体字段名。"""


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    requires_auth: bool = False
    personalized: bool = False


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    min_host_version: str
    entry: str
    capabilities: set[str]
    kinds: list[str]
    feeds: list[Feed]
    path: Path
    description: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""
    theme_color: str = ""
    cli_allow: list[list[str]] = field(default_factory=list)
    settings: list[dict[str, Any]] = field(default_factory=list)

    # ---- 便捷属性 ----
    @property
    def entry_path(self) -> Path:
        return self.path / self.entry

    @property
    def default_feed(self) -> str:
        return self.feeds[0].id if self.feeds else "default"

    def feed_ids(self) -> list[str]:
        return [f.id for f in self.feeds]

    def setting_defaults(self) -> dict[str, Any]:
        return {s["key"]: s.get("default") for s in self.settings if s.get("key")}

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Manifest {self.id} v{self.version} caps={sorted(self.capabilities)}>"


# ---------------------------------------------------------------- semver
def _parse_semver(v: str) -> tuple[int, int, int] | None:
    if not isinstance(v, str) or not SEMVER_RE.match(v):
        return None
    return tuple(int(x) for x in v.split("."))  # type: ignore[return-value]


def semver_lt(a: str, b: str) -> bool:
    """a < b。任一非法时按 False 处理（校验阶段会单独报错）。"""
    pa, pb = _parse_semver(a), _parse_semver(b)
    if pa is None or pb is None:
        return False
    return pa < pb


# ---------------------------------------------------------------- 校验
def validate_manifest(data: Any, plugin_dir: Path | None = None,
                      host_version: str = HOST_VERSION) -> list[str]:
    """返回错误消息列表；空列表表示合格。"""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["plugin.json 必须是一个 JSON 对象"]

    if data.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion 必须是 {SCHEMA_VERSION}，当前是 {data.get('schemaVersion')!r}")

    pid = data.get("id")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        errors.append("id 必填：小写字母开头，仅含小写字母/数字/连字符，长度 2–32")

    if not isinstance(data.get("name"), str) or not data.get("name", "").strip():
        errors.append("name 必填：插件显示名")

    version = data.get("version")
    if not isinstance(version, str) or not _parse_semver(version):
        errors.append(f"version 必须是 semver（如 1.0.0），当前是 {version!r}")

    min_host = data.get("minHostVersion", "0.0.0")
    if not isinstance(min_host, str) or not _parse_semver(min_host):
        errors.append(f"minHostVersion 必须是 semver，当前是 {min_host!r}")
    elif semver_lt(host_version, min_host):
        errors.append(f"minHostVersion={min_host} 高于宿主版本 {host_version}，拒绝装载")

    entry = data.get("entry", "index.js")
    if not isinstance(entry, str) or not entry or "/" in entry or "\\" in entry:
        errors.append("entry 必须是插件目录内的文件名（不允许子路径）")
    elif plugin_dir is not None and not (Path(plugin_dir) / entry).is_file():
        errors.append(f"entry 指向的文件不存在：{entry}")

    caps = data.get("capabilities")
    if not isinstance(caps, list) or not caps:
        errors.append("capabilities 必填：至少声明一项（http / browser / cli）")
        caps = []
    else:
        unknown = [c for c in caps if c not in CAPABILITIES]
        if unknown:
            errors.append(f"未知能力：{unknown}（可选 {sorted(CAPABILITIES)}）")
        if "cli" in caps and not data.get("cli", {}).get("allow"):
            errors.append("声明了 cli 能力，但缺少 cli.allow 白名单（例如 {\"allow\": [[\"bili\"]]}）")

    allow = data.get("cli", {}).get("allow")
    if allow is not None:
        if not isinstance(allow, list) or not all(
            isinstance(a, list) and all(isinstance(x, str) for x in a) for a in allow
        ):
            errors.append("cli.allow 必须是字符串数组的数组，例如 [[\"bili\"]]")
        elif any(not a or "/" in a[0] or "\\" in a[0] for a in allow):
            errors.append("cli.allow 每项第一段必须是不带路径的裸命令名（如 bili）")

    kinds = data.get("kinds")
    if not isinstance(kinds, list) or not kinds:
        errors.append("kinds 必填：该插件会产出的卡片形态")
    else:
        bad = [k for k in kinds if k not in KINDS]
        if bad:
            errors.append(f"未知 kind：{bad}（可选 {sorted(KINDS)}）")

    feeds = data.get("feeds")
    if not isinstance(feeds, list) or not feeds:
        errors.append("feeds 必填：至少声明一条流")
        feeds = []
    else:
        ids = set()
        for f in feeds:
            if not isinstance(f, dict) or not f.get("id") or not f.get("name"):
                errors.append(f"feeds 每项必须有 id 与 name：{f!r}")
                continue
            if f["id"] in ids:
                errors.append(f"feeds.id 重复：{f['id']}")
            ids.add(f["id"])

    settings = data.get("settings", [])
    if not isinstance(settings, list):
        errors.append("settings 必须是数组")
    else:
        for s in settings:
            if not isinstance(s, dict) or not s.get("key"):
                errors.append(f"settings 每项必须有 key：{s!r}")

    return errors


def load_manifest(plugin_dir: Path | str, host_version: str = HOST_VERSION) -> Manifest:
    plugin_dir = Path(plugin_dir)
    path = plugin_dir / "plugin.json"
    if not path.is_file():
        # 打包（.ofp）场景由调用方解包后再来
        raise ManifestError(f"{plugin_dir} 下没有 plugin.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"plugin.json 不是合法 JSON：{exc}") from exc

    errors = validate_manifest(data, plugin_dir=plugin_dir, host_version=host_version)
    if errors:
        raise ManifestError(f"{plugin_dir.name}: " + "；".join(errors))

    cli_allow = [list(a) for a in (data.get("cli", {}).get("allow") or [])]
    return Manifest(
        id=data["id"],
        name=data["name"],
        version=data["version"],
        min_host_version=data.get("minHostVersion", "0.0.0"),
        entry=data.get("entry", "index.js"),
        capabilities=set(data.get("capabilities") or []),
        kinds=list(data.get("kinds") or []),
        feeds=[Feed(id=f["id"], name=f["name"],
                    requires_auth=bool(f.get("requiresAuth")),
                    personalized=bool(f.get("personalized"))) for f in data.get("feeds") or []],
        path=plugin_dir.resolve(),
        description=data.get("description", ""),
        author=data.get("author", ""),
        license=data.get("license", ""),
        homepage=data.get("homepage", ""),
        theme_color=data.get("themeColor", ""),
        cli_allow=cli_allow,
        settings=list(data.get("settings") or []),
    )
