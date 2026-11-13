"""OneFeed 统一数据模型 —— 三个平台共用一套字段。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Item:
    """一条信息流卡片。id 带平台前缀，避免跨平台撞 id。"""
    id: str                    # "douyin:7698..." / "bili:BV..." / "xhs:65f..."
    platform: str              # douyin | bili | xhs | zhihu | juejin ...
    raw_id: str                # 平台原生 id，调详情/评论用
    title: str
    author: str = ""
    author_id: str = ""
    cover: str = ""            # 可直接 <img src>
    url: str = ""              # 点击跳转
    published_at: int = 0      # 秒级 unix
    duration: int = 0          # 秒
    like: int = 0
    comment: int = 0
    share: int = 0
    view: int = 0
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
    """抖音/B站把万、亿折成字符串，统一转 int。"""
    if isinstance(n, (int, float)):
        return int(n)
    if not isinstance(n, str):
        return 0
    s = n.strip()
    mult = 1
    if s.endswith("万"):
        mult, s = 10_000, s[:-1]
    elif s.endswith("亿"):
        mult, s = 100_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0
