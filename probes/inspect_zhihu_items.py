# -*- coding: utf-8 -*-
import sqlite3, json, pathlib
db = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\onefeed.db")
con = sqlite3.connect(str(db))
rows = con.execute("""
  SELECT kind, title, cover, url, author, like_count, comment_count, share_count, view_count, tags, extra, published_at
  FROM items WHERE platform='zhihu' ORDER BY published_at DESC
""").fetchall()
print("n =", len(rows))
for i, r in enumerate(rows):
    kind, title, cover, url, author, like, comment, share, view, tags, extra, pub = r
    print(f"[{i}] kind={kind} like={like} comment={comment} view={view} cover={(cover or '')[:50]}")
    print("    title:", (title or "")[:70])
    print("    author:", author, "| url:", (url or "")[:80])
    print("    extra:", (extra or "")[:120])
