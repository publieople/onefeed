import threading, traceback, sys, json
sys.path.insert(0, ".")
from onefeed.store import Store, default_db_path

def main():
    s = Store()
    print("db", s.path, "conn ok main thread")
    out = {}

    def work():
        try:
            row = {"id": "probe:thread", "platform": "probe", "kind": "short",
                   "title": "probe", "like_count": 3, "comment_count": 1,
                   "share_count": 0, "view_count": 10, "fetched_at": 1}
            n = s.upsert_items([row])
            s.conn.execute("DELETE FROM items WHERE id='probe:thread'")
            s.conn.commit()
            out["ok"] = n
        except Exception as exc:
            out["err"] = type(exc).__name__ + ": " + str(exc)
            out["tb"] = traceback.format_exc()[-1200:]

    t = threading.Thread(target=work)
    t.start(); t.join(60)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    s.close_all()

main()
