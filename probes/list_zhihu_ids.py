import sqlite3, pathlib
db = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\onefeed.db")
con = sqlite3.connect(str(db))
for row in con.execute("SELECT id, title FROM items WHERE platform='zhihu' AND id LIKE '%article%' LIMIT 5"):
    print("ARTICLE", row)
for row in con.execute("SELECT id, title FROM items WHERE platform='zhihu' AND id LIKE '%answer%' LIMIT 3"):
    print("ANSWER", row)
