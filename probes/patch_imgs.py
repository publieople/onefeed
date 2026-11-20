
import sqlite3, json, sys
sys.stdout.reconfigure(encoding="utf-8")
db = r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\tmp\probehome\onefeed.db"
c = sqlite3.connect(db); cur = c.cursor()
cur.execute("select id, images from items where id like '%6aefeb59%'")
rid, imgs = cur.fetchone()
lst = json.loads(imgs) if imgs else []
base = lst[0] if lst else ""
if base and len(lst) < 3:
    new = [base, base + ("&" if "?" in base else "?") + "x=1", base + ("&" if "?" in base else "?") + "x=2"]
    cur.execute("update items set images=? where id=?", (json.dumps(new), rid))
    c.commit()
    print("patched", rid, len(new), base[:60])
else:
    print("skip", rid, len(lst), base[:60])
c.close()
