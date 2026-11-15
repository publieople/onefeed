from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import onefeed.smart as sm
from onefeed.store import Store


def main() -> int:
    s = Store()
    print("items", s.count())
    rows = s.conn.execute(
        "select cluster_id, count(*), count(distinct platform) from items "
        "where coalesce(cluster_id, '') != '' group by cluster_id "
        "having count(*) > 1 order by 2 desc limit 8"
    ).fetchall()
    print("multi clusters", len(rows), rows[:5])
    print("summary", json.dumps(sm.summary(s), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
