import sqlite3, sys, os, tempfile, traceback
sys.path.insert(0, ".")
from onefeed.store import Store, default_db_path, ENGAGE_RAW

db = str(default_db_path())
print("TMP", os.environ.get("TMP"), "| TEMP", os.environ.get("TEMP"), "| tempdir", tempfile.gettempdir())
sql = f"""UPDATE items SET engage_score = COALESCE((
    SELECT CASE WHEN mx.mx <= 0 THEN 0 ELSE CAST(1000.0 * (1.0 - r.pr) AS INTEGER) END
    FROM (SELECT id, PERCENT_RANK() OVER (PARTITION BY platform ORDER BY {ENGAGE_RAW} DESC) AS pr FROM items) AS r
    JOIN (SELECT platform, MAX({ENGAGE_RAW}) AS mx FROM items GROUP BY platform) AS mx ON mx.platform = items.platform
    WHERE r.id = items.id), 0)"""

def try_sql(label, setup=None):
    c = sqlite3.connect(db, timeout=10.0)
    try:
        if setup: c.execute(setup)
        c.execute(sql)
        c.commit()
        print(label, "OK")
    except Exception as e:
        print(label, "FAIL", type(e).__name__, e)
    finally:
        c.close()

try_sql("default")
try_sql("temp_store=MEMORY", "PRAGMA temp_store=MEMORY")
try_sql("temp_store=FILE+cache", "PRAGMA cache_size=-8000")
