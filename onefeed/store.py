"""SQLite 存储层（003 T29）。

三张表：items / runs / plugins。不用 ORM —— 三张表手写 SQL 更短，
而且 upsert 与游标分页的 SQL 在这里一眼能看全。

设计要点：
- 连接按线程给（刷新在后台线程里写），WAL 让读不被写阻塞
- published_at 缺失的条目存 0，排序时自然沉底，不伪造时间
- images / tags / extra 存 JSON 文本，读出来再解
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    platform      TEXT NOT NULL,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    text          TEXT NOT NULL DEFAULT '',
    author        TEXT NOT NULL DEFAULT '',
    author_id     TEXT NOT NULL DEFAULT '',
    author_avatar TEXT NOT NULL DEFAULT '',
    cover         TEXT NOT NULL DEFAULT '',
    images        TEXT NOT NULL DEFAULT '[]',
    url           TEXT NOT NULL DEFAULT '',
    published_at  INTEGER NOT NULL DEFAULT 0,
    duration      INTEGER NOT NULL DEFAULT 0,
    like_count    INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    share_count   INTEGER NOT NULL DEFAULT 0,
    view_count    INTEGER NOT NULL DEFAULT 0,
    tags          TEXT NOT NULL DEFAULT '[]',
    extra         TEXT NOT NULL DEFAULT '{}',
    cluster_id    TEXT NOT NULL DEFAULT '',
    fetched_at    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_pub ON items(published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_items_platform ON items(platform, published_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER NOT NULL DEFAULT 0,
    finished_at INTEGER NOT NULL DEFAULT 0,
    plugin      TEXT NOT NULL DEFAULT '',
    ok          INTEGER NOT NULL DEFAULT 0,
    count       INTEGER NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);

CREATE TABLE IF NOT EXISTS plugins (
    id           TEXT PRIMARY KEY,
    version      TEXT NOT NULL DEFAULT '',
    installed_at INTEGER NOT NULL DEFAULT 0,
    enabled      INTEGER NOT NULL DEFAULT 1,
    sha256       TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT ''
);
"""

# Item 字段 → items 列名（统计字段要换名）
STAT_COLUMNS = {"like": "like_count", "comment": "comment_count",
                "share": "share_count", "view": "view_count"}
JSON_COLUMNS = ("images", "tags", "extra")

SORTS = {"freshness": "i.published_at DESC, i.id DESC",
         "engagement": "(i.like_count + i.comment_count * 2 + i.share_count * 3) DESC, i.published_at DESC"}


def _state_root() -> Path:
    """复用插件运行时的状态目录解析（ONEFEED_HOME > ~/.onefeed > 仓库内 .onefeed）。"""
    try:
        from plugin_runtime.paths import state_root  # type: ignore
        return state_root()
    except Exception:  # 单独跑 store 时也能用
        return Path.cwd() / ".onefeed"


def default_db_path() -> Path:
    return _state_root() / "onefeed.db"


def encode_cursor(row: dict[str, Any]) -> str:
    return f"{int(row.get('published_at') or 0)}|{row.get('id') or ''}"


def decode_cursor(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    ts, _, ident = cursor.partition("|")
    try:
        return int(ts), ident
    except ValueError:
        return None


class Store:
    """线程安全的薄封装：每个线程一个连接（SQLite 连接不能跨线程共享）。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._migrate()

    # ------------------------------------------------------------ 连接
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _migrate(self) -> None:
        conn = self.conn
        with self._write_lock:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version >= SCHEMA_VERSION:
                return
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()

    # ------------------------------------------------------------ items
    def upsert_items(self, items: Iterable[Any]) -> int:
        """写一批 Item（dataclass）或 dict；按 id 覆盖。返回受影响行数。"""
        rows = [self._row_of(it) for it in items]
        if not rows:
            return 0
        cols = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        sql = (f"INSERT INTO items ({', '.join(cols)}) VALUES ({placeholders}) "
               f"ON CONFLICT(id) DO UPDATE SET {updates}")
        values = [[r[c] for c in cols] for r in rows]
        with self._write_lock:
            cur = self.conn.executemany(sql, values)
            self.conn.commit()
        return cur.rowcount if cur.rowcount >= 0 else len(rows)

    @staticmethod
    def _row_of(item: Any) -> dict[str, Any]:
        data = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        row: dict[str, Any] = {
            "id": str(data.get("id") or ""),
            "platform": str(data.get("platform") or ""),
            "kind": str(data.get("kind") or "article"),
            "title": str(data.get("title") or ""),
            "text": str(data.get("text") or ""),
            "author": str(data.get("author") or ""),
            "author_id": str(data.get("author_id") or ""),
            "author_avatar": str(data.get("author_avatar") or ""),
            "cover": str(data.get("cover") or ""),
            "url": str(data.get("url") or ""),
            "published_at": int(data.get("published_at") or 0),
            "duration": int(data.get("duration") or 0),
            "cluster_id": str(data.get("cluster_id") or ""),
            "fetched_at": int(data.get("fetched_at") or time.time()),
        }
        for key, col in STAT_COLUMNS.items():
            row[col] = int(data.get(key) or 0)
        for key in JSON_COLUMNS:
            value = data.get(key)
            row[key] = json.dumps(value if value is not None else ([] if key != "extra" else {}),
                                  ensure_ascii=False)
        return row

    def page(self, platforms: Sequence[str] | None = None, kind: str | None = None,
             sort: str = "freshness", cursor: str | None = None,
             limit: int = 30) -> tuple[list[dict[str, Any]], str | None]:
        """游标分页：返回 (rows, next_cursor)。next_cursor 为 None 表示到底了。"""
        limit = max(1, min(int(limit), 100))
        order = SORTS.get(sort, SORTS["freshness"])
        where: list[str] = []
        params: list[Any] = []
        if platforms:
            where.append(f"i.platform IN ({', '.join('?' for _ in platforms)})")
            params.extend(platforms)
        if kind:
            where.append("i.kind = ?")
            params.append(kind)
        decoded = decode_cursor(cursor)
        if decoded:
            ts, ident = decoded
            where.append("(i.published_at < ? OR (i.published_at = ? AND i.id < ?))")
            params.extend([ts, ts, ident])
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"SELECT i.* FROM items i {clause} ORDER BY {order} LIMIT ?"
        params.append(limit + 1)
        rows = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        has_more = len(rows) > limit
        rows = rows[:limit]
        for row in rows:
            self._decode_row(row)
        next_cursor = encode_cursor(rows[-1]) if has_more and rows else None
        return rows, next_cursor

    @staticmethod
    def _decode_row(row: dict[str, Any]) -> None:
        for key in JSON_COLUMNS:
            raw = row.get(key)
            try:
                row[key] = json.loads(raw) if isinstance(raw, str) and raw else ([] if key != "extra" else {})
            except json.JSONDecodeError:
                row[key] = [] if key != "extra" else {}
        # 前端习惯的名字
        row["stats"] = {"like": row.get("like_count", 0), "comment": row.get("comment_count", 0),
                        "share": row.get("share_count", 0), "view": row.get("view_count", 0)}

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        self._decode_row(data)
        return data

    def count(self, platform: str | None = None) -> int:
        if platform:
            return int(self.conn.execute("SELECT COUNT(*) FROM items WHERE platform = ?",
                                         (platform,)).fetchone()[0])
        return int(self.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])

    def platforms(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT platform, COUNT(*) AS n, MAX(fetched_at) AS last FROM items GROUP BY platform"
        ).fetchall()
        return [{"platform": r["platform"], "count": r["n"], "last_fetched_at": r["last"]} for r in rows]

    def prune(self, keep_days: int = 14) -> int:
        """清掉太久以前的条目，避免库无限长。"""
        cutoff = int(time.time()) - keep_days * 86400
        with self._write_lock:
            cur = self.conn.execute(
                "DELETE FROM items WHERE fetched_at < ? AND published_at < ?", (cutoff, cutoff))
            self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------ runs
    def start_run(self, plugin: str) -> int:
        with self._write_lock:
            cur = self.conn.execute(
                "INSERT INTO runs (started_at, plugin) VALUES (?, ?)", (int(time.time()), plugin))
            self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, ok: bool, count: int, error: str = "") -> None:
        with self._write_lock:
            self.conn.execute(
                "UPDATE runs SET finished_at = ?, ok = ?, count = ?, error = ? WHERE id = ?",
                (int(time.time()), 1 if ok else 0, int(count), error[:500], run_id))
            self.conn.commit()

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ plugins
    def upsert_plugin(self, plugin_id: str, version: str, sha256: str = "",
                      source: str = "registry", enabled: bool = True) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO plugins (id, version, installed_at, enabled, sha256, source) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version, sha256=excluded.sha256, "
                "source=excluded.source, installed_at=excluded.installed_at, enabled=excluded.enabled",
                (plugin_id, version, int(time.time()), 1 if enabled else 0, sha256, source))
            self.conn.commit()

    def delete_plugin(self, plugin_id: str) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM plugins WHERE id = ?", (plugin_id,))
            self.conn.commit()

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        with self._write_lock:
            self.conn.execute("UPDATE plugins SET enabled = ? WHERE id = ?",
                              (1 if enabled else 0, plugin_id))
            self.conn.commit()

    def list_plugins(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM plugins ORDER BY id").fetchall()
        return [dict(r) for r in rows]
