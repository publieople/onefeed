"""Adapter registry：platform -> adapter class。"""
from __future__ import annotations

from typing import Any

from .cli_adapters import BiliCliAdapter, XhsCliAdapter
from .douyin_browser import DouyinBrowserAdapter
from .simple_adapters import JuejinAdapter, V2exAdapter, ZhihuDailyAdapter
from .models import Comment, Item

REGISTRY = {
    "bili": BiliCliAdapter,
    "xhs": XhsCliAdapter,
    "douyin": DouyinBrowserAdapter,
    "juejin": JuejinAdapter,
    "v2ex": V2exAdapter,
    "zhihu": ZhihuDailyAdapter,
}


def make(platform: str, **kwargs: Any):
    if platform not in REGISTRY:
        raise KeyError(f"未注册的平台: {platform}（有 {list(REGISTRY)}）")
    return REGISTRY[platform](**kwargs)


__all__ = ["REGISTRY", "make", "Item", "Comment", "BiliCliAdapter", "XhsCliAdapter",
           "DouyinBrowserAdapter", "JuejinAdapter", "V2exAdapter", "ZhihuDailyAdapter"]
