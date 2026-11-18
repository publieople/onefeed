"""图集灯箱的静态约束：必须走 portal、贴视口、锁滚动，别再被页壳的 transform 拽成整页高。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "src" / "pages" / "ItemPage.tsx"


def main() -> int:
    src = PAGE.read_text(encoding="utf-8")
    checks = {
        "用了 createPortal": "createPortal(" in src,
        "挂到 document.body": "document.body," in src,
        "灯箱层级独立": 'fixed inset-0 z-[60]' in src,
        "打开时锁住页面滚动": 'document.body.style.overflow = "hidden"' in src,
        "关闭时恢复滚动": "document.body.style.overflow = prev" in src,
        "长图能看原尺寸": "cursor-zoom-in" in src and "cursor-zoom-out" in src,
        "左右键翻图": "ArrowRight" in src and "ArrowLeft" in src,
        "缩略图高度有上限": "max-h-[70vh]" in src,
    }
    bad = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items():
        print(("OK   " if ok else "FAIL ") + name)
    if bad:
        print("FAILS:", ", ".join(bad))
        return 1
    print("PASS", len(checks), "checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
