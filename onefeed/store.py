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
import re
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 5

_CJK = re.compile(r"[\u3400-\u9fff]")


@lru_cache(maxsize=256)
def _word_boundary(term: str) -> re.Pattern[str]:
    """英文/数字词按词边界匹配：AI 不该命中 said、main、rail。

    LIKE %AI% 在 127 条 B 站数据里假命中 7 条（23%），这就是补它的那一刀。
    """
    return re.compile(r"(?<![0-9a-z])" + re.escape(term) + r"(?![0-9a-z])")

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
    fetched_at    INTEGER NOT NULL DEFAULT 0,
    engage_score  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_pub ON items(published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_items_platform ON items(platform, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_engage ON items(engage_score DESC, published_at DESC);

CREATE TABLE IF NOT EXISTS details (
    item_id    TEXT PRIMARY KEY,
    payload    TEXT NOT NULL DEFAULT '{}',
    fetched_at INTEGER NOT NULL DEFAULT 0
);

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

# v3 才有 details 表；老库升级时单独建，新库走上面的 SCHEMA。
DETAILS_SCHEMA = """
CREATE TABLE IF NOT EXISTS details (
    item_id    TEXT PRIMARY KEY,
    payload    TEXT NOT NULL DEFAULT '{}',
    fetched_at INTEGER NOT NULL DEFAULT 0
);
"""

# v4 的 AI 总结缓存。总结比详情更贵（要跑模型），所以按 item_id 永久存，
# 只有用户点「重算」才覆盖；basis 记素材来源，前端据此决定要不要写「依据」那一行。
SUMMARIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    item_id    TEXT PRIMARY KEY,
    payload    TEXT NOT NULL DEFAULT '{}',
    fetched_at INTEGER NOT NULL DEFAULT 0
);
"""

# Item 字段 → items 列名（统计字段要换名）
STAT_COLUMNS = {"like": "like_count", "comment": "comment_count",
                "share": "share_count", "view": "view_count"}
JSON_COLUMNS = ("images", "tags", "extra")

# 没有发布时间时（小红书首页流、知乎热榜就不给），排序按「采集时间 - 24h」估个位：
# 真正新鲜的先上，无时间的也不会永远沉底；显示层仍然不写时间，不编造。
FRESH_KEY = "COALESCE(NULLIF(i.published_at, 0), i.fetched_at - 86400)"
# 跨平台不能直接比计数（B 站 5 千播放和知乎 400 万热度不是一个量级），
# 所以热度统一用「本平台内分位」：刷新后重算 engage_score（0–1000），排序只比这个分。
ENGAGE_RAW = "(like_count + comment_count * 2 + share_count * 3 + view_count * 0.05)"
ENGAGE_KEY = "i.engage_score"

SORTS = {"freshness": f"{FRESH_KEY} DESC, i.id DESC",
         "engagement": f"{ENGAGE_KEY} DESC, {FRESH_KEY} DESC, i.id DESC"}
SORT_KEYS = {"freshness": FRESH_KEY, "engagement": ENGAGE_KEY}


AGENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_threads (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id            TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'running',   -- running/done/error/cancelled
    input         TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    reply         TEXT NOT NULL DEFAULT '',
    steps         INTEGER NOT NULL DEFAULT 0,
    ms            INTEGER NOT NULL DEFAULT 0,
    tokens        INTEGER NOT NULL DEFAULT 0,
    error         TEXT NOT NULL DEFAULT '',
    created_at    INTEGER NOT NULL,
    finished_at   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread
    ON agent_runs(thread_id, created_at DESC);
CREATE TABLE IF NOT EXISTS agent_steps (             -- 事件流水：回放 + 审计
    run_id        TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    payload       TEXT NOT NULL DEFAULT '{}',
    undo_token    TEXT NOT NULL DEFAULT '',
    at            INTEGER NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS item_marks (              -- 收藏 / 已读 / 隐藏
    item_id       TEXT PRIMARY KEY,
    saved         INTEGER NOT NULL DEFAULT 0,
    read_at       INTEGER NOT NULL DEFAULT 0,
    hidden        INTEGER NOT NULL DEFAULT 0,
    updated_at    INTEGER NOT NULL DEFAULT 0
);
"""


def _state_root() -> Path:
    """复用插件运行时的状态目录解析（ONEFEED_HOME > ~/.onefeed > 仓库内 .onefeed）。"""
    try:
        from plugin_runtime.paths import state_root  # type: ignore
        return state_root()
    except Exception:  # 单独跑 store 时也能用
        return Path.cwd() / ".onefeed"


def default_db_path() -> Path:
    return _state_root() / "onefeed.db"


def sort_value(row: dict[str, Any], sort: str) -> int:
    if sort == "engagement":
        return int(row.get("engage_score") or 0)
    return int(row.get("published_at") or 0) or max(0, int(row.get("fetched_at") or 0) - 86400)


def encode_cursor(row: dict[str, Any], sort: str = "freshness") -> str:
    return f"{sort_value(row, sort)}|{row.get('id') or ''}"


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
        self._all_conns: list[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        self._migrate()

    # ------------------------------------------------------------ 连接
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            # 窗口函数（热度分位）要临时空间；本机用户 Temp 目录不可写时
            # SQLite 会直接报 "unable to open database file"，所以固定走内存。
            # 条目量级（万级以内）内存完全够，不必落盘换页。
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
            with self._conns_lock:
                self._all_conns.append(conn)
        return conn

    def close(self) -> None:
        """关掉本线程的连接。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def close_all(self) -> None:
        """关掉所有线程的连接 —— 测试与进程退出时用，否则 Windows 删不掉库文件。"""
        with self._conns_lock:
            conns, self._all_conns = self._all_conns, []
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._local.conn = None

    def _migrate(self) -> None:
        conn = self.conn
        with self._write_lock:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version >= SCHEMA_VERSION:
                return
            if version < 1:
                conn.executescript(SCHEMA)
            if version < 2:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
                if "engage_score" not in columns:
                    conn.execute("ALTER TABLE items ADD COLUMN engage_score INTEGER NOT NULL DEFAULT 0")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_items_engage "
                             "ON items(engage_score DESC, published_at DESC)")
            if version < 3:
                conn.executescript(DETAILS_SCHEMA)
            if version < 4:
                conn.executescript(SUMMARIES_SCHEMA)
            if version < 5:
                conn.executescript(AGENT_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        self.recompute_engage()

    def recompute_engage(self) -> None:
        """按平台内分位重算热度分（0–1000）：跨平台比计数没有意义，比名次才有。

        同一平台内数据全为 0（比如没有互动字段的论坛帖）就记 0，
        免得所有条目并列满分、把别的平台挤下去。
        """
        sql = f"""
        UPDATE items SET engage_score = COALESCE((
            SELECT CASE WHEN mx.mx <= 0 THEN 0
                        ELSE CAST(1000.0 * (1.0 - r.pr) AS INTEGER) END
            FROM (SELECT id, PERCENT_RANK() OVER (
                      PARTITION BY platform ORDER BY {ENGAGE_RAW} DESC) AS pr
                  FROM items) AS r
            JOIN (SELECT platform, MAX({ENGAGE_RAW}) AS mx FROM items GROUP BY platform) AS mx
              ON mx.platform = items.platform
            WHERE r.id = items.id
        ), 0)
        """
        with self._write_lock:
            self.conn.execute(sql)
            self.conn.commit()

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
        self.recompute_engage()
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
             limit: int = 30, keyword: str | None = None,
             since: int | None = None, saved: bool = False) -> tuple[list[dict[str, Any]], str | None]:
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
        if keyword:
            kw = f"%{keyword.strip()}%"
            where.append("(i.title LIKE ? OR i.text LIKE ? OR i.author LIKE ?)")
            params.extend([kw, kw, kw])
        if since:
            where.append(f"{FRESH_KEY} >= ?")
            params.append(int(since))
        if saved:
            # 只看我收藏的：Agent 存的条目、手点星标的条目都在这里
            where.append("m.saved = 1")
        decoded = decode_cursor(cursor)
        if decoded:
            ts, ident = decoded
            key = SORT_KEYS.get(sort, FRESH_KEY)
            where.append(f"({key} < ? OR ({key} = ? AND i.id < ?))")
            params.extend([ts, ts, ident])
        where.append("COALESCE(m.hidden, 0) = 0")  # 「不感兴趣」的条目默认不进流
        clause = "WHERE " + " AND ".join(where)
        sql = (f"SELECT i.*, m.saved AS mark_saved, m.read_at AS mark_read_at, "
               f"m.hidden AS mark_hidden "
               f"FROM items i LEFT JOIN item_marks m ON m.item_id = i.id "
               f"{clause} ORDER BY {order} LIMIT ?")
        params.append(limit + 1)
        rows = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        has_more = len(rows) > limit
        rows = rows[:limit]
        for row in rows:
            self._decode_row(row)
        next_cursor = encode_cursor(rows[-1], sort) if has_more and rows else None
        return rows, next_cursor

    # ------------------------------------------------------------ 检索
    @staticmethod
    def _hit_score(terms: Sequence[str], row: dict[str, Any]) -> float:
        """一个条目对一组词的加权命中分：标题×3、正文×1、作者×0.2。

        英文/数字词按词边界，中文按子串（中文没空格，边界无从谈起）。
        同一个词在同一字段里只记一次，免得长正文靠复读刷分。
        """
        title = str(row.get("title") or "").lower()
        text = str(row.get("text") or "").lower()
        author = str(row.get("author") or "").lower()
        score = 0.0
        for raw in terms:
            term = str(raw or "").strip().lower()
            if not term:
                continue
            if _CJK.search(term):
                hits = (term in title, term in text, term in author)
            else:
                pattern = _word_boundary(term)
                hits = (bool(pattern.search(title)), bool(pattern.search(text)),
                        bool(pattern.search(author)))
            score += 3.0 * hits[0] + 1.0 * hits[1] + 0.2 * hits[2]
        return score

    def search_items(self, terms: Sequence[str] | None = None,
                     platforms: Sequence[str] | None = None, kind: str | None = None,
                     sort: str = "freshness", limit: int = 12,
                     since: int | None = None, duration_min: int | None = None,
                     duration_max: int | None = None, like_min: int | None = None,
                     exclude: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """带权检索：先按硬条件取候选池，再按词打分。

        与 page(keyword=...) 的区别：多个词是「或」不是整串 LIKE，标题命中
        权重更高，时长 / 点赞是真过滤。terms 为空就退化成候选池（browse 用）。
        """
        limit = max(1, min(int(limit), 60))
        pool = max(60, limit * 5)  # 池子太小会让打分失灵：好条目根本没进候选
        where: list[str] = []
        params: list[Any] = []
        if platforms:
            where.append(f"i.platform IN ({', '.join('?' for _ in platforms)})")
            params.extend(platforms)
        if kind:
            where.append("i.kind = ?")
            params.append(kind)
        if since:
            where.append(f"{FRESH_KEY} >= ?")
            params.append(int(since))
        if duration_min:
            where.append("i.duration >= ?")
            params.append(int(duration_min))
        if duration_max:
            where.append("i.duration <= ?")
            params.append(int(duration_max))
        if like_min:
            where.append("i.like_count >= ?")
            params.append(int(like_min))
        if exclude:
            ids = [str(x) for x in exclude][:200]
            where.append(f"i.id NOT IN ({', '.join('?' for _ in ids)})")
            params.extend(ids)
        where.append("COALESCE(m.hidden, 0) = 0")
        clause = "WHERE " + " AND ".join(where)
        sql = (f"SELECT i.*, m.saved AS mark_saved, m.read_at AS mark_read_at, "
               f"m.hidden AS mark_hidden "
               f"FROM items i LEFT JOIN item_marks m ON m.item_id = i.id "
               f"{clause} ORDER BY {SORTS.get(sort, SORTS['freshness'])} LIMIT ?")
        params.append(pool)
        rows = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        for row in rows:
            self._decode_row(row)
        cleaned = [str(t).strip() for t in (terms or []) if str(t or "").strip()][:8]
        if cleaned:
            scored = [(self._hit_score(cleaned, row), row) for row in rows]
            scored = [(s, r) for s, r in scored if s > 0]
            # sorted 是稳定的：分数相同的仍按 SQL 的排序（新鲜度/热度）
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [row for _score, row in scored[:limit]]
        return rows[:limit]

    def cluster_items(self, cluster_id: str, exclude_id: str = "",
                      limit: int = 6) -> list[dict[str, Any]]:
        """同一件事的其它平台说法（cluster_id 由 smart.cluster 算出来）。"""
        if not cluster_id:
            return []
        rows = self.conn.execute(
            "SELECT i.* FROM items i WHERE i.cluster_id = ? AND i.id != ? "
            f"ORDER BY {ENGAGE_KEY} DESC LIMIT ?",
            (cluster_id, exclude_id, max(1, min(int(limit), 20)))).fetchall()
        out = [dict(r) for r in rows]
        for row in out:
            self._decode_row(row)
        return out

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
        # 收藏 / 已读 / 隐藏：真值放 item_marks，这里拍平成布尔给前端
        for key, mark in (("saved", "mark_saved"), ("read", "mark_read_at"),
                          ("hidden", "mark_hidden")):
            row[key] = bool(row.pop(mark, 0) or 0)

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT i.*, m.saved AS mark_saved, m.read_at AS mark_read_at, "
            "m.hidden AS mark_hidden "
            "FROM items i LEFT JOIN item_marks m ON m.item_id = i.id WHERE i.id = ?",
            (item_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        self._decode_row(data)
        return data

    # ------------------------------------------------------------ details
    def get_detail(self, item_id: str, max_age: int = 0) -> dict[str, Any] | None:
        """取详情缓存。max_age>0 时过期当作没有（调用方决定要不要重抓）。"""
        row = self.conn.execute(
            "SELECT item_id, payload, fetched_at FROM details WHERE item_id = ?",
            (item_id,)).fetchone()
        if row is None:
            return None
        fetched_at = int(row["fetched_at"] or 0)
        if max_age > 0 and int(time.time()) - fetched_at > max_age:
            return None
        try:
            payload = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return {"item_id": row["item_id"], "payload": payload, "fetched_at": fetched_at}

    def save_detail(self, item_id: str, payload: dict[str, Any]) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO details (item_id, payload, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET payload=excluded.payload, "
                "fetched_at=excluded.fetched_at",
                (item_id, json.dumps(payload, ensure_ascii=False), int(time.time())))
            self.conn.commit()

    def drop_detail(self, item_id: str) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM details WHERE item_id = ?", (item_id,))
            self.conn.commit()

    # ------------------------------------------------------------ agent
    # 011：会话 / 运行 / 步骤 / 条目标记。轨迹先落库再吐 SSE：
    # 刷新页面能回放，进程重启也不丢。
    def ensure_thread(self, thread_id: str, title: str = "") -> None:
        now = int(time.time())
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO agent_threads (id, title, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at, "
                "title=CASE WHEN excluded.title != '' THEN excluded.title ELSE agent_threads.title END",
                (thread_id, title[:200], now, now))
            self.conn.commit()

    def start_agent_run(self, run_id: str, thread_id: str = "", input_text: str = "",
                        model: str = "") -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO agent_runs (id, thread_id, status, input, model, created_at) "
                "VALUES (?, ?, 'running', ?, ?, ?)",
                (run_id, thread_id, input_text[:2000], model[:120], int(time.time())))
            self.conn.commit()
        if thread_id:
            self.ensure_thread(thread_id, title=input_text[:60])

    def finish_agent_run(self, run_id: str, status: str = "done", reply: str = "",
                         error: str = "", steps: int = 0, ms: int = 0,
                         tokens: int = 0) -> None:
        with self._write_lock:
            self.conn.execute(
                "UPDATE agent_runs SET status=?, reply=?, error=?, steps=?, ms=?, tokens=?, "
                "finished_at=? WHERE id=?",
                (status, reply[:4000], error[:1000], int(steps), int(ms), int(tokens),
                 int(time.time()), run_id))
            self.conn.commit()

    def add_agent_step(self, run_id: str, seq: int, kind: str, name: str = "",
                       payload: dict[str, Any] | None = None, undo_token: str = "") -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO agent_steps "
                "(run_id, seq, kind, name, payload, undo_token, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, int(seq), kind, name[:120],
                 json.dumps(payload or {}, ensure_ascii=False), undo_token, int(time.time())))
            self.conn.commit()

    @staticmethod
    def _decode_step(row: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = json.loads(row.get("payload") or "{}")
        except json.JSONDecodeError:
            payload = {}
        return {"seq": int(row.get("seq") or 0), "kind": row.get("kind") or "",
                "name": row.get("name") or "", "at": int(row.get("at") or 0),
                "undo_token": row.get("undo_token") or "",
                "data": payload if isinstance(payload, dict) else {}}

    def get_agent_run(self, run_id: str, steps: bool = True) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        if steps:
            rows = self.conn.execute(
                "SELECT seq, kind, name, payload, undo_token, at FROM agent_steps "
                "WHERE run_id = ? ORDER BY seq", (run_id,)).fetchall()
            data["events"] = [self._decode_step(dict(r)) for r in rows]
        return data

    def recent_agent_runs(self, thread_id: str | None = None, limit: int = 20,
                          steps: bool = False) -> list[dict[str, Any]]:
        """最近跑过的 run。steps=True 时顺带把每轮的事件读出来（设置页活动列表要拿 undo_token）。"""
        limit = max(1, min(int(limit), 100))
        if thread_id:
            rows = self.conn.execute(
                "SELECT * FROM agent_runs WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
                (thread_id, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = [dict(r) for r in rows]
        if steps:
            for run in out:
                events = self.conn.execute(
                    "SELECT seq, kind, name, payload, undo_token, at FROM agent_steps "
                    "WHERE run_id = ? ORDER BY seq", (run["id"],)).fetchall()
                run["events"] = [self._decode_step(dict(r)) for r in events]
        return out

    def recent_threads(self, limit: int = 20) -> list[dict[str, Any]]:
        """会话列表：一条线 = 一段连续的对话。标题取第一句话，附轮数与最后一次时间。"""
        limit = max(1, min(int(limit), 100))
        rows = self.conn.execute(
            "SELECT t.id, t.title, t.created_at, t.updated_at, "
            "(SELECT COUNT(*) FROM agent_runs r WHERE r.thread_id = t.id) AS runs, "
            "(SELECT reply FROM agent_runs r WHERE r.thread_id = t.id AND r.reply != '' "
            " ORDER BY r.created_at DESC LIMIT 1) AS last_reply "
            "FROM agent_threads t ORDER BY t.updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def thread_runs(self, thread_id: str, limit: int = 40,
                    steps: bool = True) -> list[dict[str, Any]]:
        """一轮对话里每一问一答：时间正序，方便直接铺成聊天记录。

        steps=True 时把每轮的完整事件带回去。结果卡片、计划、轨迹全在 done 事件的
        payload 里，只回放 input/reply 的话「上次给我看的那几条」就丢了。
        """
        limit = max(1, min(int(limit), 100))
        rows = self.conn.execute(
            "SELECT id, input, reply, status, steps, ms, error, created_at, finished_at "
            "FROM agent_runs WHERE thread_id = ? ORDER BY created_at ASC LIMIT ?",
            (thread_id, limit)).fetchall()
        out = [dict(r) for r in rows]
        if steps:
            for run in out:
                events = self.conn.execute(
                    "SELECT seq, kind, name, payload, undo_token, at FROM agent_steps "
                    "WHERE run_id = ? ORDER BY seq", (run["id"],)).fetchall()
                run["events"] = [self._decode_step(dict(r)) for r in events]
        return out

    def get_mark(self, item_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM item_marks WHERE item_id = ?",
                                (item_id,)).fetchone()
        if row is None:
            return {"item_id": item_id, "saved": False, "read": False, "hidden": False,
                    "read_at": 0}
        return {"item_id": item_id, "saved": bool(row["saved"]), "read": bool(row["read_at"]),
                "hidden": bool(row["hidden"]), "read_at": int(row["read_at"] or 0),
                "updated_at": int(row["updated_at"] or 0)}

    def mark_item(self, item_id: str, saved: bool | None = None, read: bool | None = None,
                  hidden: bool | None = None) -> dict[str, Any]:
        """局部更新标记：只改传了的那几项，没传的保持原值。"""
        current = self.get_mark(item_id)
        if saved is not None:
            current["saved"] = bool(saved)
        if read is not None:
            current["read"] = bool(read)
            current["read_at"] = int(time.time()) if read else 0
        if hidden is not None:
            current["hidden"] = bool(hidden)
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO item_marks (item_id, saved, read_at, hidden, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(item_id) DO UPDATE SET "
                "saved=excluded.saved, read_at=excluded.read_at, hidden=excluded.hidden, "
                "updated_at=excluded.updated_at",
                (item_id, int(current["saved"]), int(current["read_at"]),
                 int(current["hidden"]), int(time.time())))
            self.conn.commit()
        return self.get_mark(item_id)

    def saved_items(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT i.*, m.saved AS mark_saved, m.read_at AS mark_read_at, "
            "m.hidden AS mark_hidden "
            "FROM item_marks m JOIN items i ON i.id = m.item_id "
            "WHERE m.saved = 1 AND COALESCE(m.hidden, 0) = 0 "
            "ORDER BY m.updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),)).fetchall()
        out = [dict(r) for r in rows]
        for row in out:
            self._decode_row(row)
        return out

    # ------------------------------------------------------------ summaries
    def get_summary(self, item_id: str) -> dict[str, Any] | None:
        """取 AI 总结缓存。总结按条永久存，不看时间——要看新的就 refresh。"""
        row = self.conn.execute(
            "SELECT item_id, payload, fetched_at FROM summaries WHERE item_id = ?",
            (item_id,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or not payload:
            return None
        return {"item_id": row["item_id"], "payload": payload,
                "fetched_at": int(row["fetched_at"] or 0)}

    def save_summary(self, item_id: str, payload: dict[str, Any]) -> None:
        with self._write_lock:
            self.conn.execute(
                "INSERT INTO summaries (item_id, payload, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET payload=excluded.payload, "
                "fetched_at=excluded.fetched_at",
                (item_id, json.dumps(payload, ensure_ascii=False), int(time.time())))
            self.conn.commit()

    def drop_summary(self, item_id: str) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM summaries WHERE item_id = ?", (item_id,))
            self.conn.commit()

    def update_clusters(self, mapping: dict[str, str]) -> int:
        """把 {item_id: cluster_id} 写回，用于 T45 的同题合并。"""
        if not mapping:
            return 0
        with self._write_lock:
            self.conn.executemany("UPDATE items SET cluster_id = ? WHERE id = ?",
                                  [(cid, iid) for iid, cid in mapping.items()])
            self.conn.commit()
        return len(mapping)

    def cluster_sizes(self, cluster_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """给一批 cluster_id 查各自有几条、涉及哪些平台。"""
        ids = [c for c in dict.fromkeys(cluster_ids) if c]
        if not ids:
            return {}
        marks = ", ".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT cluster_id, COUNT(*) AS n, GROUP_CONCAT(platform) AS ps "
            f"FROM items WHERE cluster_id IN ({marks}) GROUP BY cluster_id", ids).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            platforms = sorted(set(str(r["ps"] or "").split(","))) if r["ps"] else []
            out[r["cluster_id"]] = {"size": int(r["n"]), "platforms": platforms}
        return out

    def all_titles(self) -> list[tuple[str, str, str]]:
        """(id, platform, title)，供同题合并用。"""
        rows = self.conn.execute("SELECT id, platform, title FROM items").fetchall()
        return [(r["id"], r["platform"], r["title"] or "") for r in rows]

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