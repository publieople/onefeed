"""换主题动效的静态回归：CSS 与组件里那几处「必须存在」的写法。

真效果由 probes/check_theme_reveal.py 在真浏览器里验（需要服务在跑）；
这里只守住三件事，防止哪天重构把 View Transition 悄悄弄丢：
1. theme.css 里有 ::view-transition-group / reveal-light / reveal-dark 与两组 polygon；
2. theme.ts 有 runThemeTransition：不支持或不适合动效时直接切，不硬上；
3. TopBar 用 runThemeTransition + flushSync，换色与图标同帧。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "web" / "src" / "theme.css").read_text(encoding="utf-8")
THEME_TS = (ROOT / "web" / "src" / "theme.ts").read_text(encoding="utf-8")
TOPBAR = (ROOT / "web" / "src" / "components" / "TopBar.tsx").read_text(encoding="utf-8")

CASES: list[tuple[str, callable]] = []


def case(fn):
    CASES.append((fn.__name__, fn))
    return fn


@case
def test_view_transition_rules() -> None:
    for needle in (
        "::view-transition-group(root)",
        "::view-transition-new(root)",
        "::view-transition-old(root)",
        "animation-duration: 0.7s",
        "animation-name: reveal-light",
        "html.dark::view-transition-new(root)",
    ):
        assert needle in CSS, "theme.css 缺 " + needle


@case
def test_reveal_keyframes() -> None:
    assert "@keyframes reveal-dark" in CSS, "缺 reveal-dark"
    assert "@keyframes reveal-light" in CSS, "缺 reveal-light"
    # DeepWiki 的两组对角 polygon，起点终点都要在
    assert "polygon(50% -71%, -50% 71%, -50% 71%, 50% -71%)" in CSS, "reveal-dark 起点丢了"
    assert "polygon(171% 50%, 50% 171%, -50% 71%, 50% -71%)" in CSS, "reveal-light 终点丢了"
    assert "polygon(171% 50%, 50% 171%, 50% 171%, 171% 50%)" in CSS, "reveal-light 起点丢了"


@case
def test_reduced_motion_and_vt_suppression() -> None:
    assert ".theme-vt" in CSS, "缺 theme-vt 抑制规则（快照会抓到过渡起点色）"
    assert "transition: none !important" in CSS, "theme-vt 没有关掉逐元素过渡"


@case
def test_run_theme_transition_helper() -> None:
    assert "export function runThemeTransition" in THEME_TS
    assert "startViewTransition" in THEME_TS
    assert "prefers-reduced-motion" in THEME_TS, "没给减少动态效果的用户留直切"
    assert "theme-vt" in THEME_TS, "没加/没清 theme-vt 类"


@case
def test_topbar_uses_helper() -> None:
    assert "runThemeTransition" in TOPBAR
    assert "flushSync" in TOPBAR, "换色与图标不在同一帧，图标会慢半拍"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("  PASS", name)
        except AssertionError as exc:
            failed += 1
            print("  FAIL", name, exc)
    print(f"test_theme_reveal: {len(CASES) - failed}/{len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
