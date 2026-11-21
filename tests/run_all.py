"""跑全部验收脚本。

跑法：
    uv run python tests/run_all.py            # 全跑（含联网的 real / e2e）
    uv run python tests/run_all.py --offline  # 跳过联网用例

每个 test_*.py 是自带 main() 的独立脚本，用退出码表示通过与否；
这里只负责按顺序跑、汇总、并在失败时给出可复现的单项命令。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

OFFLINE_SKIP = {"test_store_real.py", "test_e2e_feed.py"}
ORDER = [
    "test_store.py",
    "test_store_real.py",
    "test_api.py",
    "test_settings.py",
    "test_auth_flow.py",
    "test_market_update.py",
    "test_media.py",
    "test_preflight.py",
    "test_ai.py",
    "test_agent.py",
    "test_agent_runtime.py",
    "test_agent_tasks.py",
    "test_summary.py",
    "test_favorites.py",
    "test_refresh.py",
    "test_ui_lint.py",
    "test_theme_reveal.py",
    "test_nav_motion.py",
    "test_feed_filters.py",
    "test_lightbox.py",
    "test_entry.py",
    "test_e2e_feed.py",
    "test_interaction.py",
    "test_card_actions.py",
    "test_nav_motion.py",
    "test_grid_cols.py",
    "test_infinite_and_rail.py",
    "test_side_rails.py",
    "test_motion_coverage.py",
]


def _last_line(text: str) -> str:
    for line in reversed(text.strip().splitlines()):
        if line.strip():
            return line.strip()
    return ""


def main() -> int:
    root = Path(__file__).resolve().parent
    offline = "--offline" in sys.argv
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(root.parent)}

    failed: list[str] = []
    for name in ORDER:
        if offline and name in OFFLINE_SKIP:
            print(f"跳过 {name}（--offline）")
            continue
        started = time.time()
        proc = subprocess.run(
            [sys.executable, str(root / name)],
            cwd=str(root.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        ms = int((time.time() - started) * 1000)
        ok = proc.returncode == 0
        tail = _last_line(proc.stdout)
        print(f"{'✅' if ok else '❌'} {name:<22} {ms:>6} ms  {tail}")
        if not ok:
            failed.append(name)
            detail = (proc.stdout + proc.stderr).strip().splitlines()
            for line in detail[-8:]:
                print("   | " + line)

    if failed:
        print()
        print("失败：" + ", ".join(failed))
        print("单项复现：uv run python tests/" + failed[0])
        return 1
    print()
    print(f"全部通过（{len(ORDER) - (2 if offline else 0)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
