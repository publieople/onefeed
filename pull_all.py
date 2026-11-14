"""本地试跑：经插件运行时拉一轮信息流，打印统一字段。

插件不在本仓库里（见 onefeed-plugins），所以要先指到插件目录：
    python pull_all.py                                   # 默认 ../onefeed-plugins/plugins
    python pull_all.py zhihu-hot juejin --limit 10
    python pull_all.py --plugins-dir probes/plugins zhihu-hot
    python pull_all.py --json > out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK，打印 ♥ 💬 会崩；统一转 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from plugin_runtime import PluginHost  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugins", nargs="*", help="插件 id；省略则跑目录下全部")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--pages", type=int, default=1, help="每个插件拉几页（插件返回 next 才继续）")
    ap.add_argument("--plugins-dir", default=None)
    ap.add_argument("--json", action="store_true", help="只输出 JSON，便于管道")
    args = ap.parse_args()

    host = PluginHost(plugins_dir=args.plugins_dir)
    manifests = host.discover()
    for err in host.errors:
        print(f"[skip] {err}", file=sys.stderr)
    if not manifests:
        print(f"插件目录 {host.plugins_dir} 里没有可用插件", file=sys.stderr)
        return 1

    ids = args.plugins or [m.id for m in manifests]
    print(f"插件目录: {host.plugins_dir}", file=sys.stderr)

    collected = []
    failures = []
    for pid in ids:
        print(f"--- {pid} ---", file=sys.stderr)
        try:
            for _ in range(max(1, args.pages)):
                collected.extend(host.pull(pid, limit=args.limit))
        except Exception as exc:  # 单插件失败不影响其它插件
            failures.append({"plugin": pid, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{pid}] 失败: {type(exc).__name__}: {exc}", file=sys.stderr)

    collected.sort(key=lambda x: x.published_at, reverse=True)
    if args.json:
        print(json.dumps({"items": [i.to_dict() for i in collected], "failures": failures},
                         ensure_ascii=False, indent=2))
        return 0 if collected else 1

    print(f"\n共 {len(collected)} 条" + (f"，{len(failures)} 个插件失败" if failures else ""))
    for it in collected:
        when = datetime.fromtimestamp(it.published_at).strftime("%m-%d %H:%M") if it.published_at else "--"
        print(f"[{it.platform:12}] {when} {it.kind:7} ♥{it.like:>7} 💬{it.comment:>5} | "
              f"{it.author[:10]:10} | {it.title[:34]}")
        print(f"         cover: {it.cover[:78] or '(无)'}")
    for f in failures:
        print(f"[FAIL] {f['plugin']}: {f['error'][:160]}")
    return 0 if collected else 1


if __name__ == "__main__":
    raise SystemExit(main())
