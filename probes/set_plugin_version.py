import sys
sys.path.insert(0, ".")
from onefeed.store import Store

plugin_id = sys.argv[1]
version = sys.argv[2]
s = Store()
s.conn.execute("UPDATE plugins SET version=? WHERE id=?", (version, plugin_id))
s.conn.commit()
for row in s.conn.execute("SELECT id, version, enabled FROM plugins ORDER BY id"):
    print(tuple(row))
s.close_all()
