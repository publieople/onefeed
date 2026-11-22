"""把 fixtures 变成静态演示站要的一份快照（012-demo-site）。

跑法：
    uv run python scripts/export_demo.py
    uv run python scripts/export_demo.py --out /tmp/api.json

产物只有一份 api.json：meta / health / summary / settings / feed。
字段形状与本地实例一致（都从真实 API 截下来），只抹掉本机路径、把图片换成 https。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from onefeed import __version__, smart  # noqa: E402
from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

PAGE = 100
DEFAULT_OUT = ROOT / "web" / "public" / "demo" / "api.json"

# 这些域名有 TLS，http:// 换成 https:// 不会被 pages 的混合内容策略拦
HTTPS_HOSTS = (
    "hdslb.com", "bilibili.com", "xhscdn.com", "xiaohongshu.com",
    "douyinpic.com", "douyin.com", "byteacctimg.com", "zhimg.com", "zhihu.com",
    "juejin.cn", "v2ex.com", "sinaimg.cn",
)


# fixtures 里偶有别人贴出的密钥（V2EX 正文真见过 sk-...），快照不再继续扩散
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def mask_secrets(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(0)[:3] + "***（已隐去）", text)
    return text


def to_https(url: Any) -> Any:
    if not isinstance(url, str) or not url.startswith("http://"):
        return url
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in HTTPS_HOSTS):
        return "https://" + url[len("http://"):]
    return url


def scrub(node: Any) -> Any:
    """递归把可换的 http 图片地址换成 https，其它值原样返回。"""
    if isinstance(node, str):
        return mask_secrets(to_https(node))
    if isinstance(node, list):
        return [scrub(v) for v in node]
    if isinstance(node, dict):
        return {k: scrub(v) for k, v in node.items()}
    return node


def load_fixtures(store: Store) -> tuple[int, dict[str, int]]:
    """与 service._load 读同一批文件，但直接 upsert（不经过插件发现）。"""
    saved: dict[str, int] = {}
    total = 0
    for path in sorted(ROOT.joinpath("fixtures").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  跳过 {path.name}：{exc}")
            continue
        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            print(f"  跳过 {path.name}：没有 items")
            continue
        n = store.upsert_items(items)
        total += n
        pid = str(payload.get("plugin") or path.stem)
        saved[pid] = int(payload.get("saved_at") or 0)
        print(f"  {pid:<12} {n:>4} 条  ({path.name})")
    return total, saved


def collect_feed(client: TestClient) -> tuple[list[dict], int]:
    items: list[dict] = []
    seen: set[str] = set()
    cursor: str | None = None
    count = 0
    for _ in range(50):  # 硬上限：50 页 × 100，够任何人用
        params: dict[str, Any] = {"limit": PAGE}
        if cursor:
            params["cursor"] = cursor
        resp = client.get("/api/feed", params=params)
        resp.raise_for_status()
        body = resp.json()
        count = int(body.get("count") or 0)
        for row in body.get("items") or []:
            rid = str(row.get("id") or "")
            if rid and rid not in seen:
                seen.add(rid)
                items.append(row)
        cursor = body.get("next")
        if not cursor:
            break
    return items, count or len(items)


def build(out: Path) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="onefeed-demo-"))
    old_home = os.environ.get("ONEFEED_HOME")
    old_demo = os.environ.get("ONEFEED_DEMO")
    os.environ["ONEFEED_HOME"] = str(tmp)
    # 快照就是演示：health.demo / summary.offline 都该是 true
    os.environ["ONEFEED_DEMO"] = "1"
    try:
        store = Store(tmp / "demo.db")
        print("读 fixtures：")
        loaded, saved = load_fixtures(store)
        if not loaded:
            raise SystemExit("fixtures 里没有可用条目，先跑一次 --warmup")

        # 同平台/同话题聚类，否则卡片上的「相关 N 条」全是空的
        clusters = smart.cluster(store)
        print(f"聚类：{clusters} 组")

        client = TestClient(create_app(store))

        feed_items, count = collect_feed(client)
        platforms = sorted({str(i.get("platform") or "") for i in feed_items if i.get("platform")})
        health = client.get("/api/health").json()
        # 插件数按快照里真正有数据的平台算：CI 是干净环境，导出机的插件目录不能带进来
        health["plugins"] = len(platforms)
        summary = client.get("/api/summary").json()
        settings = client.get("/api/settings").json()

        # 本机路径与凭证不出快照
        health["db"] = ""
        resolved = settings.get("resolved")
        if isinstance(resolved, dict):
            resolved["state_dir"] = ""
            resolved["plugins_dir"] = ""
        for key in list(settings.get("settings") or {}):
            if key.endswith("_key") or key.endswith("_token"):
                settings["settings"][key] = ""
        for provider in settings.get("settings", {}).get("ai_providers") or []:
            if isinstance(provider, dict) and "api_key" in provider:
                provider["api_key"] = ""

        newest = max((int(i.get("published_at") or 0) for i in feed_items), default=0)
        snapshot = {
            "meta": {
                "generated_at": int(time.time()),
                "version": __version__,
                "items": len(feed_items),
                "newest_published_at": newest,
                "fixtures_saved_at": saved,
                "platforms": platforms,
            },
            "health": scrub(health),
            "summary": scrub(summary),
            "settings": scrub(settings),
            "feed": {"items": scrub(feed_items), "count": count, "next": None, "parsed": None},
        }
    finally:
        if old_home is None:
            os.environ.pop("ONEFEED_HOME", None)
        else:
            os.environ["ONEFEED_HOME"] = old_home
        if old_demo is None:
            os.environ.pop("ONEFEED_DEMO", None)
        else:
            os.environ["ONEFEED_DEMO"] = old_demo
        shutil.rmtree(tmp, ignore_errors=True)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmpfile = out.with_suffix(out.suffix + ".tmp")
    tmpfile.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmpfile.replace(out)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="导出静态演示站快照")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出路径（默认 web/public/demo/api.json）")
    args = parser.parse_args()

    started = time.time()
    snap = build(args.out)
    size = args.out.stat().st_size
    meta = snap["meta"]
    print(f"\n快照：{args.out}")
    print(f"  条目 {meta['items']} 条 / 平台 {len(meta['platforms'])} 个 / {size / 1024:.0f} KB / {time.time() - started:.1f}s")
    if size > 2 * 1024 * 1024:
        print("  警告：超过 2 MB，Pages 能放但首屏会慢")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
