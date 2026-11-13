"""免登录 HTTP adapter：掘金推荐流、V2EX 热帖、知乎日报。

这三个都是纯 JSON 公开接口，不需要 cookie、不需要签名，是最便宜的信息流来源。
（2026-11-13 本机实测全部 200）
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

from .models import Comment, Item, clamp

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"


PROXY_CANDIDATES = ("", "http://127.0.0.1:7890", "http://127.0.0.1:10809")


def http_json(url: str, body: dict | None = None, timeout: int = 15) -> Any:
    """直连失败就换本地代理重试。显式构造 ProxyHandler：
    本机 NO_PROXY 含 [::1]，任何读环境代理的库（httpx/urllib）都会解析崩。"""
    data = json.dumps(body).encode() if body is not None else None
    last: Exception | None = None
    for proxy in PROXY_CANDIDATES:
        handlers = {"http": proxy, "https": proxy} if proxy else {}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(handlers))
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        })
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw)
        except Exception as exc:
            last = exc
            continue
    raise RuntimeError(f"HTTP 取数失败（直连+代理均不通）: {type(last).__name__}: {last}")


class JuejinAdapter:
    """掘金推荐流：POST /recommend_api/v1/article/recommend_all_feed，免登录。"""
    platform = "juejin"
    URL = "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"

    def __init__(self, log: Callable[[str], None] = print):
        self.log = log

    def start(self) -> None: self.log("[juejin] 免登录 HTTP")
    def close(self) -> None: pass
    def __enter__(self): self.start(); return self
    def __exit__(self, *exc): self.close()

    def pull(self, limit: int = 20) -> list[Item]:
        payload = http_json(self.URL, {"id_type": 2, "client_type": 2608, "sort_type": 200,
                                       "cursor": "0", "limit": max(1, min(limit, 30))})
        out: list[Item] = []
        for row in payload.get("data") or []:
            info = row.get("item_info") or {}
            art = info.get("article_info") or {}
            if not art.get("article_id"):
                continue
            user = info.get("author_user_info") or {}
            out.append(Item(
                id=f"juejin:{art['article_id']}", platform="juejin", raw_id=art["article_id"],
                title=(art.get("title") or "").strip()[:200],
                author=user.get("user_name") or "",
                author_id=user.get("user_id") or "",
                cover=(art.get("cover_image") or ""),
                url=f"https://juejin.cn/post/{art['article_id']}",
                published_at=clamp(art.get("ctime")),
                duration=0,
                like=clamp(art.get("digg_count")),
                comment=clamp(art.get("comment_count")),
                view=clamp(art.get("view_count")),
                extra={"collect": clamp(art.get("collect_count")),
                       "brief": (art.get("brief_content") or "")[:120],
                       "tags": [t.get("tag_name") for t in (info.get("tags") or [])]},
            ))
            if len(out) >= limit:
                break
        self.log(f"[juejin] pull 拿到 {len(out)} 条")
        return out

    def comments(self, item: Item, limit: int = 20) -> list[Comment]:
        raise NotImplementedError("掘金评论走 POST /interact_api/v1/comment_list")


class V2exAdapter:
    """V2EX 热帖：官方公开 API，免登录。"""
    platform = "v2ex"
    URL = "https://www.v2ex.com/api/topics/hot.json"

    def __init__(self, log: Callable[[str], None] = print):
        self.log = log

    def start(self) -> None: self.log("[v2ex] 免登录 HTTP")
    def close(self) -> None: pass
    def __enter__(self): self.start(); return self
    def __exit__(self, *exc): self.close()

    def pull(self, limit: int = 20) -> list[Item]:
        rows = http_json(self.URL)
        out: list[Item] = []
        for t in rows or []:
            node = t.get("node") or {}
            member = t.get("member") or {}
            out.append(Item(
                id=f"v2ex:{t.get('id')}", platform="v2ex", raw_id=str(t.get("id")),
                title=(t.get("title") or "").strip()[:200],
                author=member.get("username") or "",
                author_id=str(member.get("id") or ""),
                cover="",
                url=t.get("url") or f"https://www.v2ex.com/t/{t.get('id')}",
                published_at=clamp(t.get("created")),
                comment=clamp(t.get("replies")),
                extra={"node": node.get("title") or node.get("name"),
                       "content": (t.get("content") or "")[:160]},
            ))
            if len(out) >= limit:
                break
        self.log(f"[v2ex] pull 拿到 {len(out)} 条")
        return out

    def comments(self, item: Item, limit: int = 20) -> list[Comment]:
        d = http_json(f"https://www.v2ex.com/api/topics/show.json?id={item.raw_id}")
        out: list[Comment] = []
        for t in d or []:
            for r in (t.get("replies") or [])[:limit]:
                out.append(Comment(id=f"v2ex:{r.get('id')}", platform="v2ex", item_id=item.id,
                                   author=(r.get("member") or {}).get("username") or "",
                                   text=(r.get("content") or "")[:500],
                                   created_at=clamp(r.get("created"))))
        return out


class ZhihuDailyAdapter:
    """知乎日报：老接口一直活着，免登录，带配图。"""
    platform = "zhihu"
    URL = "https://news-at.zhihu.com/api/4/news/latest"

    def __init__(self, log: Callable[[str], None] = print):
        self.log = log

    def start(self) -> None: self.log("[zhihu] 知乎日报 免登录 HTTP")
    def close(self) -> None: pass
    def __enter__(self): self.start(); return self
    def __exit__(self, *exc): self.close()

    def pull(self, limit: int = 20) -> list[Item]:
        d = http_json(self.URL)
        out: list[Item] = []
        for s in d.get("stories") or []:
            imgs = s.get("images") or []
            out.append(Item(
                id=f"zhihu:{s.get('id')}", platform="zhihu", raw_id=str(s.get("id")),
                title=(s.get("title") or "").strip()[:200],
                cover=imgs[0] if imgs else "",
                url=s.get("url") or f"https://daily.zhihu.com/story/{s.get('id')}",
                published_at=0,
                extra={"hint": s.get("hint")},
            ))
            if len(out) >= limit:
                break
        self.log(f"[zhihu] pull 拿到 {len(out)} 条（{d.get('date')}）")
        return out

    def comments(self, item: Item, limit: int = 20) -> list[Comment]:
        return []
