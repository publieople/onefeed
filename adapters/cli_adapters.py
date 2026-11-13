"""CLI 路线 adapter：B 站走 bili，小红书走 xhs。子进程必须喂干净 env（NO_PROXY 坑）。"""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

from .models import Comment, Item, clamp

SAFE_ENV_KEYS = ("PATH", "SystemRoot", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                 "TEMP", "TMP", "PYTHONUTF8", "PYTHONIOENCODING", "HOMEDRIVE", "HOMEPATH")


def clean_env() -> dict[str, str]:
    """去掉 HTTP(S)_PROXY / NO_PROXY —— 本机 NO_PROXY 含 [::1] 会让 httpx 直接崩。"""
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


TOOL_DIRS = {
    "bili": ["bili", "bili-agent"],
    "xhs": ["xhs", "xhs-cli"],
    "dy": ["dy", "dy-cli"],
}


def tool_path(name: str) -> str:
    """uv tool 装的包名和可执行名不一致（bili 装在 bili-agent 目录），按候选目录找。"""
    base = os.path.expanduser(r"~\AppData\Roaming\uv\tools")
    for d in TOOL_DIRS.get(name, [name]):
        exe = os.path.join(base, d, "Scripts", name + ".exe")
        if os.path.exists(exe):
            return exe
    from shutil import which
    found = which(name) or which(name + ".exe")
    if found:
        return found
    raise FileNotFoundError(f"{name} 未安装（uv tool install 对应包）")


def run_json(exe: str, args: list[str], timeout: int = 60) -> dict[str, Any]:
    proc = subprocess.run([exe, *args], capture_output=True, text=True,
                          encoding="utf-8", env=clean_env(), timeout=timeout)
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError((proc.stderr or "空输出").strip()[:200])
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"非 JSON 输出: {out[:200]}")
    if payload.get("ok") is False:
        err = payload.get("error") or {}
        raise RuntimeError(f"{err.get('code')}: {err.get('message')}")
    return payload.get("data", payload)


class BiliCliAdapter:
    platform = "bili"

    def __init__(self, fetch_covers: int = 8, log: Callable[[str], None] = print):
        self.exe = tool_path("bili")
        self.fetch_covers = fetch_covers
        self.log = log

    def start(self) -> None:
        self.log(f"[bili] {self.exe}")

    def close(self) -> None:
        pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def pull(self, limit: int = 20) -> list[Item]:
        data = run_json(self.exe, ["feed", "recommend", "--count", str(max(1, min(limit, 30)))])
        items = [self._normalize(x) for x in data.get("items") or []]
        items = [x for x in items if x]
        if self.fetch_covers:
            self._fill_covers(items[: self.fetch_covers])
        items.sort(key=lambda x: x.published_at, reverse=True)
        self.log(f"[bili] pull 拿到 {len(items)} 条（personalized={data.get('personalized')}）")
        return items

    def _normalize(self, it: dict) -> Item | None:
        bvid = it.get("bvid")
        if not bvid:
            return None
        author = it.get("author") or {}
        stat = it.get("stat") or {}
        ts = 0
        raw_pub = it.get("pubdate")
        if isinstance(raw_pub, str):
            try:
                ts = int(datetime.fromisoformat(raw_pub).timestamp())
            except ValueError:
                ts = 0
        elif isinstance(raw_pub, (int, float)):
            ts = int(raw_pub)
        return Item(
            id=f"bili:{bvid}", platform="bili", raw_id=bvid,
            title=(it.get("title") or "").strip()[:200],
            author=author.get("name") or "", author_id=str(author.get("mid") or ""),
            cover=it.get("pic") or "",
            url=it.get("url") or f"https://www.bilibili.com/video/{bvid}",
            published_at=ts, duration=clamp(it.get("duration")),
            like=clamp(stat.get("like")), comment=clamp(stat.get("reply")),
            view=clamp(stat.get("view")),
            extra={"followed": bool(it.get("followed_author")), "danmaku": clamp(stat.get("danmaku"))},
        )

    def _fill_covers(self, items: list[Item]) -> None:
        def one(item: Item) -> None:
            try:
                d = run_json(self.exe, ["video", "info", item.raw_id, "--raw"], timeout=30)
                item.cover = item.cover or (d.get("pic") or "")
                stat = d.get("stat") or {}
                item.comment = item.comment or clamp(stat.get("reply"))
                item.like = item.like or clamp(stat.get("like"))
                item.view = item.view or clamp(stat.get("view"))
            except Exception:
                pass

        if items:
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(one, items))

    def comments(self, item: Item, limit: int = 20) -> list[Comment]:
        d = run_json(self.exe, ["comment", "list", item.raw_id, "--sort", "hot", "--page", "1"])
        out: list[Comment] = []
        for c in d.get("items") or []:
            user = c.get("user") or {}
            out.append(Comment(
                id=f"bili:{c.get('rpid')}", platform="bili", item_id=item.id,
                author=user.get("name") or "", text=(c.get("content") or "")[:500],
                like=clamp(c.get("like")), reply_count=clamp(c.get("reply_count")),
                created_at=clamp(c.get("time")),
            ))
            if len(out) >= limit:
                break
        return out


class XhsCliAdapter:
    platform = "xhs"

    def __init__(self, log: Callable[[str], None] = print):
        self.exe = tool_path("xhs")
        self.log = log
        self.logged_in = False

    def start(self) -> None:
        # xhs status 是纯文本（勾/叉 + 一行提示），不是 JSON
        proc = subprocess.run([self.exe, "status"], capture_output=True, text=True,
                              encoding="utf-8", env=clean_env(), timeout=60)
        text = (proc.stdout or "") + (proc.stderr or "")
        self.logged_in = ("Not logged in" not in text) and ("未登录" not in text) and bool(text.strip())
        self.log(f"[xhs] 登录态={self.logged_in}")

    def close(self) -> None:
        pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def pull(self, limit: int = 20) -> list[Item]:
        if not self.logged_in:
            raise RuntimeError("小红书未登录，先跑 xhs login 扫码")
        d = run_json(self.exe, ["feed", "--json"])
        raw = d.get("items") or d.get("notes") or d.get("data") or []
        out = [x for x in (self._normalize(n) for n in raw) if x]
        self.log(f"[xhs] pull 拿到 {len(out)} 条")
        return out[:limit]

    def _normalize(self, n: dict) -> Item | None:
        nid = n.get("note_id") or n.get("id")
        if not nid:
            return None
        user = n.get("user") or {}
        cover = ""
        ic = n.get("cover") or n.get("image") or {}
        if isinstance(ic, dict):
            cover = ic.get("url_default") or ic.get("url") or ""
        interact = n.get("interact_info") or {}
        return Item(
            id=f"xhs:{nid}", platform="xhs", raw_id=str(nid),
            title=((n.get("title") or n.get("display_title") or n.get("desc") or "")[:200]).strip(),
            author=user.get("nickname") or user.get("name") or "",
            author_id=user.get("user_id") or user.get("id") or "",
            cover=cover, url=f"https://www.xiaohongshu.com/explore/{nid}",
            published_at=0, duration=0,
            like=clamp(interact.get("liked_count")),
            comment=clamp(interact.get("comment_count")),
            extra={"type": n.get("type")},
        )

    def comments(self, item: Item, limit: int = 20) -> list[Comment]:
        raise NotImplementedError("xhs comment 命令只发评论；读评论走 xhs read --json")
