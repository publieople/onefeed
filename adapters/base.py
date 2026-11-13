"""Adapter 契约：一个平台一个实现，统一 pull / comments。"""
from __future__ import annotations

from typing import Protocol

from .models import Comment, Item


class Adapter(Protocol):
    platform: str

    def start(self) -> None: ...
    def pull(self, limit: int = 20) -> list[Item]: ...
    def comments(self, item: Item, limit: int = 20) -> list[Comment]: ...
    def close(self) -> None: ...
