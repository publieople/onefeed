import sqlite3, collections, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
c = sqlite3.connect(r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\onefeed.db")
rows = c.execute("select platform,title,published_at,fetched_at from items").fetchall()
print("total", len(rows))
cnt = collections.Counter((p,t) for p,t,_,_ in rows)
dup = [(k,v) for k,v in cnt.items() if v>1]
print("dup titles", len(dup), dup[:5])
print("by day", collections.Counter(__import__("datetime").datetime.fromtimestamp(p).strftime("%m-%d") if p else "0" for _,_,p,_ in rows))
