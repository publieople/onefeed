# -*- coding: utf-8 -*-
"""列出抖音与小红书各几条真实条目的 url，供评论探针使用。"""
import sqlite3
DB = r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\onefeed.db"
c = sqlite3.connect(DB)
for platform in ("douyin", "xiaohongshu"):
    rows = c.execute(
        "select id, kind, substr(title,1,40), url from items where platform=? order by published_at desc limit 8",
        (platform,),
    ).fetchall()
    print("=== " + platform + " ===")
    for r in rows:
        print(r[0], "|", r[1], "|", r[2], "|", r[3])
