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
# 能力（capabilities）说的是"插件能调什么"，feature 说的是"插件对外提供什么额外内容"。
# 评论/详情/媒体都是可选能力：认领了才调，没认领的平台照常出卡片。
FEATURES = {"comments", "detail", "media", "summary", "following_accounts", "author_posts"}
# 宿主能渲染的整站嵌入只有这两家：B 站官方播放器、抖音官方播放器。
# 其它平台（小红书/知乎/快手…）一律走插件自渲染正文，别拿 iframe 硬套。
EMBED_PROVIDERS = {"bilibili", "douyin"}
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
HOST_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

# 清单只描述"要读哪个插件自己的文件"，不能拿它当任意文件读/命令执行的入口。
STATE_TOKEN = "${state}"
APP_TOKEN = "${appdata}"
LOCALAPP_TOKEN = "${localappdata}"
HOME_TOKEN = "${home}"
SEED_TO_PREFIX = STATE_TOKEN + "/"
SEED_FROM_PREFIXES = (STATE_TOKEN + "/", APP_TOKEN + "/", LOCALAPP_TOKEN + "/", HOME_TOKEN + "/")

CLI_BANNED_COMMANDS = re.compile(
    r"^(?:python|pythonw|pypy|py|node|nodejs|deno|bun|powershell|pwsh|cmd|bash|sh|zsh|fish|"
    r"perl|ruby|php|wscript|cscript|mshta|rundll32|regsvr32|curl|wget|certutil|bitsadmin|"
    r"schtasks|wmic|reg|sc|netsh|taskkill)(?:[\d.]*)?(?:\.exe)?$",
    re.I,
)
CLI_ENV_DENY = {
    "PATH", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE",
    "NODE_OPTIONS", "NODE_PATH", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "COMSPEC", "PATHEXT", "SHELL",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
    "SYSTEMROOT", "WINDIR", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
}


def _has_parent_ref(value: str) -> bool:
    return ".." in re.split(r"[\\/]+", value)


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
    cli_env: dict[str, str] = field(default_factory=dict)      # 子进程额外的环境变量（支持 ${state} 等占位）
    cli_seed: list[dict[str, str]] = field(default_factory=list)  # 首次调用前把本机文件复制进隔离目录
    settings: list[dict[str, Any]] = field(default_factory=list)
    features: set[str] = field(default_factory=set)
    embeds: list[str] = field(default_factory=list)        # 允许嵌的播放器：bilibili / douyin
    media_hosts: list[str] = field(default_factory=list)   # 边车可注 Cookie 的域（*.xhscdn.com）

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
        return f"<Manifest {self.id} v{self.version} caps={sorted(self.capabilities)} features={sorted(self.features)}>"


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
        elif any(CLI_BANNED_COMMANDS.match(a[0]) for a in allow):
            errors.append("cli.allow 不允许解释器/下载器（python/node/powershell/cmd/curl 等）")

    cli_env = data.get("cli", {}).get("env")
    if cli_env is not None:
        if not isinstance(cli_env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in cli_env.items()
        ):
            errors.append("cli.env 必须是 \"变量名 -> 值\" 的对象，值只能是字符串")
        else:
            bad_keys = sorted(k for k in cli_env if k.upper() in CLI_ENV_DENY)
            if bad_keys:
                errors.append(f"cli.env 不允许覆盖这些环境变量：{bad_keys}")
            if any(
                _has_parent_ref(v)
                and any(v.startswith(p) for p in SEED_FROM_PREFIXES)
                for v in cli_env.values()
            ):
                errors.append("cli.env 里以占位符开头的路径不允许包含 ..")

    cli_seed = data.get("cli", {}).get("seed")
    if cli_seed is not None:
        if not isinstance(cli_seed, list) or not all(
            isinstance(s, dict) and isinstance(s.get("from"), str) and isinstance(s.get("to"), str)
            for s in cli_seed
        ):
            errors.append("cli.seed 必须是 [{\"from\": \"…\", \"to\": \"…\"}] 数组")
        else:
            for s in cli_seed:
                # 源只允许宿主的私有目录/用户目录；目标只允许宿主状态目录。
                if not any(s["from"].startswith(p) for p in SEED_FROM_PREFIXES):
                    errors.append(f"cli.seed.from 必须以 {STATE_TOKEN}/、{APP_TOKEN}/、{LOCALAPP_TOKEN}/ 或 {HOME_TOKEN}/ 开头：{s['from']!r}")
                elif _has_parent_ref(s["from"]):
                    errors.append(f"cli.seed.from 不允许包含 ..：{s['from']!r}")
                if not s["to"].startswith(SEED_TO_PREFIX):
                    # 只允许把文件复制到宿主的私有状态目录里，不能往系统任意位置写
                    errors.append(f"cli.seed 的 to 必须以 {STATE_TOKEN}/ 开头（只能写宿主的私有状态目录）")
                elif _has_parent_ref(s["to"]):
                    errors.append(f"cli.seed.to 不允许包含 ..：{s['to']!r}")

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

    features = data.get("features", [])
    if not isinstance(features, list):
        errors.append(f"features 必须是数组（可选 {sorted(FEATURES)}）")
    else:
        bad = [f for f in features if f not in FEATURES]
        if bad:
            errors.append(f"未知 feature：{bad}（可选 {sorted(FEATURES)}）")
        if "media" in features and "detail" not in features:
            errors.append("声明了 media 就要同时声明 detail：媒体地址只能从详情里来")

    embeds = data.get("embeds", [])
    if not isinstance(embeds, list) or not all(isinstance(e, str) for e in embeds):
        errors.append("embeds 必须是字符串数组，例如 [\"bilibili\"]")
    else:
        bad = [e for e in embeds if e not in EMBED_PROVIDERS]
        if bad:
            errors.append(f"未知 embed 提供方：{bad}（宿主只渲染 {sorted(EMBED_PROVIDERS)}）")

    media_hosts = data.get("mediaHosts", [])
    if not isinstance(media_hosts, list) or not all(isinstance(h, str) for h in media_hosts):
        errors.append("mediaHosts 必须是字符串数组，例如 [\"*.xhscdn.com\"]")
    else:
        bad = [h for h in media_hosts if not HOST_RE.match(h)]
        if bad:
            errors.append(f"mediaHosts 每项必须是不带协议的域名（可带 *. 前缀）：{bad}")

    settings = data.get("settings", [])
    if not isinstance(settings, list):
        errors.append("settings 必须是数组")
    else:
        for s in settings:
            if not isinstance(s, dict) or not s.get("key"):
                errors.append(f"settings 每项必须有 key：{s!r}")
                continue
            default = s.get("default")
            if s.get("key") in {"cookieFile", "browserProfile"} and isinstance(default, str) and default:
                if not default.startswith(SEED_TO_PREFIX) or _has_parent_ref(default):
                    errors.append(f"settings.{s['key']} 默认值必须落在 {STATE_TOKEN}/ 下且不能包含 ..")

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
    cli_env = {str(k): str(v) for k, v in (data.get("cli", {}).get("env") or {}).items()}
    cli_seed = [{"from": s["from"], "to": s["to"]} for s in (data.get("cli", {}).get("seed") or [])]
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
        cli_env=cli_env,
        cli_seed=cli_seed,
        settings=list(data.get("settings") or []),
        features=set(data.get("features") or []),
        embeds=list(data.get("embeds") or []),
        media_hosts=list(data.get("mediaHosts") or []),
    )
