import sqlite3, pathlib
db = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\onefeed.db")
con = sqlite3.connect(str(db))
cur = con.execute("SELECT COUNT(*) FROM details WHERE item_id LIKE 'zhihu:%'")
print("before:", cur.fetchone()[0])
con.execute("DELETE FROM details WHERE item_id LIKE 'zhihu:%'")
con.commit()
print("after:", con.execute("SELECT COUNT(*) FROM details WHERE item_id LIKE 'zhihu:%'").fetchone()[0])
print("total details:", con.execute("SELECT COUNT(*) FROM details").fetchone()[0])
