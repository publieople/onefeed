"""图集灯箱的静态约束：必须走 portal、贴视口、锁滚动，别再被页壳的 transform 拽成整页高。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "src" / "pages" / "ItemPage.tsx"
LOCK = ROOT / "web" / "src" / "motion" / "useScrollLock.ts"
NAV = ROOT / "web" / "src" / "motion" / "nav.ts"
THEME = ROOT / "web" / "src" / "theme.css"


def main() -> int:
    src = PAGE.read_text(encoding="utf-8")
    checks = {
        "用了 createPortal": "createPortal(" in src,
        "挂到 document.body": "document.body," in src,
        "灯箱层级独立": 'fixed inset-0 z-[60]' in src,
        # 锁的是 html（documentElement）而不是 body：body 锁了 html 还能滚，
        # 实测灯箱打开时页面照样 0→175。锁与还原都收进 useScrollLock。
        "打开时锁住页面滚动": "useScrollLock(true)" in src,
        "不再手写 body 锁": "document.body.style.overflow" not in src,
        "锁与还原在 hook 里": 'html.style.overflow = "hidden"' in LOCK.read_text(encoding="utf-8")
        and "html.style.overflow = saved.overflow" in LOCK.read_text(encoding="utf-8"),
        "长图能看原尺寸": "cursor-zoom-in" in src and "cursor-zoom-out" in src,
        "左右键翻图": "ArrowRight" in src and "ArrowLeft" in src,
        "缩略图高度有上限": "max-h-[70vh]" in src,
        # 缩略图与灯箱大图会同时在 DOM 里，名字常驻在 img 上会让新快照出现两个 of-lb，
        # 浏览器会把整段共享元素转场降级掉——看起来就是没有缩放、直接跳出来。
        "大图不常驻共享名": 'style={{ viewTransitionName: "of-lb" }}' not in src,
        "大图有可接管的标记": 'data-lb-image=""' in src,
        "打开时把名字交给大图": "afterApply" in src and 'img.style.viewTransitionName = "of-lb"' in src,
        "关闭时把名字交回缩略图": 'thumb.style.viewTransitionName = "of-lb"' in src,
        # 关闭若还走 lightbox 组，CSS 会按“打开方向”把旧快照藏掉，看不到缩回
        "关闭走反向组": 'runNav("back", () => setLightbox(null)' in src,
        "转场器支持换边挂名": "afterApply?: () => void;" in NAV.read_text(encoding="utf-8"),
        "灯箱有缩放曲线": "::view-transition-group(of-lb)" in THEME.read_text(encoding="utf-8")
        and "nav-lb-in" in THEME.read_text(encoding="utf-8")
        and "nav-lb-out" in THEME.read_text(encoding="utf-8"),
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
