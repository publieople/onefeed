"""本地试跑：拉一轮多个平台，打印统一字段，验证 adapter 契约。

用法（仓库根目录下）：
    python pull_all.py douyin bili
    python pull_all.py douyin --limit 10 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK，打印 ♥ 💬 会崩；统一转 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from adapters import make  # noqa: E402


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("platforms", nargs="*", default=["douyin", "bili"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="只输出 JSON，便于管道")
    args = ap.parse_args()

    collected = []
    for name in args.platforms:
        print(f"--- {name} ---", file=sys.stderr)
        try:
            kwargs = {"log": log} if name in ("douyin", "bili", "xhs") else {}
            adapter = make(name, **kwargs)
            adapter.start()
            items = adapter.pull(limit=args.limit)
            adapter.close()
        except Exception as exc:  # 单平台失败不影响其它平台
            print(f"[{name}] 失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        collected.extend(items)

    collected.sort(key=lambda x: x.published_at, reverse=True)
    if args.json:
        print(json.dumps([i.to_dict() for i in collected], ensure_ascii=False, indent=2))
        return
    print(f"\n共 {len(collected)} 条")
    for it in collected:
        when = it.published_at and __import__("datetime").datetime.fromtimestamp(it.published_at).strftime("%m-%d %H:%M") or "--"
        print(f"[{it.platform:6}] {when} ♥{it.like:>6} 💬{it.comment:>4} | {it.author[:10]:10} | {it.title[:34]}")
        print(f"         cover: {it.cover[:78] or '(无)'}")


if __name__ == "__main__":
    main()
