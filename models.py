"""OneFeed 统一数据模型 —— 宿主内部与插件输出之间的中间层。

插件交上来的是"平台无关"的 RawItem（见 specs/002-plugin-arch/spec.md §7），
宿主用 `to_item()` 把它拼成带平台前缀 id 的 Item，再入库/排序/渲染。
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Item:
    """一条信息流卡片。id 带平台前缀，避免跨平台撞 id。"""

    id: str                    # "douyin:7698..." / "bili:BV..." / "xhs:65f..."
    platform: str              # 插件 id：bilibili | xiaohongshu | douyin | juejin | v2ex | zhihu-hot
    raw_id: str                # 平台原生 id，调详情/评论用
    title: str
    kind: str = "article"      # video | images | article | short | list
    text: str = ""             # 摘要/正文纯文本
    author: str = ""
    author_id: str = ""
    author_avatar: str = ""
    cover: str = ""            # 可直接 <img src>
    images: list[str] = field(default_factory=list)
    url: str = ""              # 点击跳转
    published_at: int = 0      # 秒级 unix
    duration: int = 0          # 秒
    like: int = 0
    comment: int = 0
    share: int = 0
    view: int = 0
    tags: list[str] = field(default_factory=list)
    fetched_at: int = field(default_factory=lambda: int(time.time()))
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Comment:
    id: str
    platform: str
    item_id: str               # 对应 Item.id
    author: str
    text: str
    like: int = 0
    reply_count: int = 0
    created_at: int = 0
    replies: list["Comment"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def clamp(n: Any) -> int:
    """抖音/B站/知乎把万、亿折成字符串，统一转 int。"""
    if isinstance(n, bool):
        return int(n)
    if isinstance(n, (int, float)):
        return int(n)
    if not isinstance(n, str):
        return 0
    s = n.strip().replace(",", "")
    mult = 1
    if s.endswith("万"):
        mult, s = 10_000, s[:-1]
    elif s.endswith("亿"):
        mult, s = 100_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0
