"""交互质量门禁：把 web/scripts/check-ui.mjs 接进测试链。

门禁只查能直接弄坏暗色模式或动效一致性的写法（写死 bg-white、写死阴影、
写死时长）。它不评价设计，只防止回归。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
SCRIPT = WEB / "scripts" / "check-ui.mjs"

CASES: list[tuple[str, callable]] = []


def case(fn):
    CASES.append((fn.__name__, fn))
    return fn


def _run() -> tuple[int, str, str]:
    node = shutil.which("node")
    if not node:
        return (127, "", "node not found")
    proc = subprocess.run(
        [node, str(SCRIPT), "--json"],
        cwd=str(WEB),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    return (proc.returncode, proc.stdout, proc.stderr)


@case
def test_ui_lint_passes() -> None:
    code, out, err = _run()
    if code == 127:
        raise SystemExit("SKIP: 本机没有 node，跳过 UI 门禁")
    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["ok"] is True, (
        "UI 门禁有 " + str(payload["count"]) + " 处违规：\n" + out.strip()[-2000:] + "\n" + err[-500:]
    )


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("  PASS", name)
        except SystemExit as exc:  # skip
            print("  SKIP", name, exc)
        except AssertionError as exc:
            failed += 1
            print("  FAIL", name, exc)
    print(f"test_ui_lint: {len(CASES) - failed}/{len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
