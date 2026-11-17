"""本地智能层（003 T45–T48）。

三个能力都不联网：标题归一化 + simhash 聚类、自然语言过滤解析、排序理由与一句话摘要。
断网时行为完全一致，这是演示的安全底线。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Any

# ---------------------------------------------------------------- 归一化

_PUNCT = re.compile(r"[\s\u3000!-/:-@\[-\x60{-~，。！？；：、“”‘’（）《》【】…—·|~]+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")
_TRAIL = re.compile(r"(\.{3}|…+|等)$")


def normalize_title(title: str) -> str:
    text = _EMOJI.sub("", title or "")
    text = _PUNCT.sub("", text)
    text = text.lower()
    return _TRAIL.sub("", text)


def _tokens(text: str) -> list[str]:
    norm = normalize_title(text)
    latin = re.findall(r"[a-z0-9]{2,}", norm)
    cjk = re.findall(r"[\u4e00-\u9fff]", norm)
    grams = ["".join(cjk[i:i + 2]) for i in range(len(cjk) - 1)]
    return latin + grams + cjk


def simhash(text: str, bits: int = 64) -> int:
    vector = [0] * bits
    for token in _tokens(text):
        digest = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")
        for i in range(bits):
            vector[i] += 1 if (digest >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if vector[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


# ---------------------------------------------------------------- 聚类

def cluster(store, threshold: int = 3, min_len: int = 6) -> int:
    """把同一件事的条目合成簇，写回 cluster_id。返回被写回的条目数。

    规则：标题归一化后完全相同直接同簇；否则 simhash 汉明距离 <= threshold 也算。
    标题太短的（「哈哈」）不参与，避免误合并。
    """
    rows = store.all_titles()
    by_norm: dict[str, str] = {}
    groups: list[dict[str, Any]] = []
    for item_id, platform, title in rows:
        norm = normalize_title(title)
        if len(norm) < min_len:
            continue
        if norm in by_norm:
            cid = by_norm[norm]
            for g in groups:
                if g["cluster_id"] == cid:
                    g["items"].append((item_id, platform))
                    break
            continue
        h = simhash(title)
        matched = None
        for g in groups:
            if hamming(g["simhash"], h) <= threshold:
                matched = g
                break
        if matched is None:
            cid = hashlib.blake2b(norm.encode("utf-8"), digest_size=4).hexdigest()
            groups.append({"cluster_id": cid, "simhash": h, "items": [(item_id, platform)]})
            by_norm[norm] = cid
        else:
            matched["items"].append((item_id, platform))
            by_norm[norm] = matched["cluster_id"]
    mapping: dict[str, str] = {}
    for g in groups:
        if len(g["items"]) < 2:
            mapping[g["items"][0][0]] = ""
            continue
        for item_id, _platform in g["items"]:
            mapping[item_id] = g["cluster_id"]
    for item_id, _platform, _title in rows:
        mapping.setdefault(item_id, "")
    return store.update_clusters(mapping)


# ---------------------------------------------------------------- 自然语言过滤

PLATFORM_ALIASES: dict[str, list[str]] = {
    "bilibili": ["b站", "bilibili", "哔哩哔哩", "小破站"],
    "xiaohongshu": ["小红书", "红书", "xhs"],
    "douyin": ["抖音", "douyin"],
    "juejin": ["掘金", "juejin"],
    "v2ex": ["v2ex", "v站"],
    # 先长后短：先把「知乎热榜」剥掉，剩下的「知乎」才是推荐流，不然热榜会把两个都吃掉
    "zhihu-hot": ["知乎热榜", "zhihu-hot", "热榜"],
    "zhihu": ["知乎", "zhihu"],
}
KIND_ALIASES: dict[str, list[str]] = {
    "video": ["视频", "短视频"],
    "images": ["图文", "图片", "图集"],
    "article": ["文章", "长文"],
    "short": ["动态"],
    "list": ["榜单", "排行", "热榜"],
}
_STOPWORDS = ["只看", "看看", "看", "的", "和", "与", "在", "里", "有", "内容", "信息", "然后",
              "给我", "帮我", "我", "要", "找", "一点", "今天", "昨天", "本周", "这周", "里"]


def _alias_regex(alias: str) -> str:
    """把 'b站' 编成 'b\\s*站'，这样「B 站」这种中间带空格的写法也能命中。"""
    return "\\s*".join(re.escape(ch) for ch in alias)


def _strip_alias(work: str, alias: str, flags=re.IGNORECASE) -> tuple[str, bool]:
    pattern = re.compile(_alias_regex(alias), flags)
    found = pattern.search(work) is not None
    return (pattern.sub(" ", work), found)


def parse_query(text: str, now: int | None = None) -> dict[str, Any]:
    """把「只看今天 B 站的 AI 视频」变成过滤参数。解析失败时退化为纯关键词。"""
    raw = (text or "").strip()
    now = int(now or time.time())
    work = raw
    platforms: list[str] = []
    for pid, alts in PLATFORM_ALIASES.items():
        hit = False
        for alias in alts:
            work, found = _strip_alias(work, alias)
            hit = hit or found
        if hit:
            platforms.append(pid)
    kinds: list[str] = []
    for kind, alts in KIND_ALIASES.items():
        hit = False
        for alias in alts:
            work, found = _strip_alias(work, alias)
            hit = hit or found
        if hit:
            kinds.append(kind)

    since = None
    today = now - (now % 86400) - 8 * 3600
    for word, offset in (("今天", 0), ("今日", 0), ("昨天", -86400), ("本周", -6 * 86400)):
        if word in work:
            since = today + offset
            work = work.replace(word, " ")
    for junk in _STOPWORDS:
        work = work.replace(junk, " ")
    words = [w for w in re.split(r"[\s,，、。;；:：!！?？~]+", work) if w.strip()]
    keyword = " ".join(words)[:40]
    return {
        "raw": raw,
        "platforms": platforms,
        "kinds": kinds,
        "since": since,
        "keyword": keyword,
        "understood": bool(platforms or kinds or since or keyword),
    }


# ---------------------------------------------------------------- 理由与摘要

PLATFORM_LABELS = {
    "bilibili": "B 站", "xiaohongshu": "小红书", "douyin": "抖音",
    "juejin": "掘金", "v2ex": "V2EX", "zhihu": "知乎", "zhihu-hot": "知乎热榜",
}


def reason_for(row: dict[str, Any], stats: dict[str, Any] | None = None) -> list[str]:
    """给一张卡编 1–3 条理由，数字都来自数据本身。"""
    out: list[str] = []
    stats = stats or {}
    if stats.get("platforms"):
        others = [p for p in stats["platforms"] if p != row.get("platform")]
        if others:
            out.append(f"另外 {len(others)} 个平台也在讲")
    published = int(row.get("published_at") or 0)
    if published:
        hours = max(0, int((time.time() - published) / 3600))
        if hours <= 1:
            out.append("1 小时内发布")
        elif hours <= 3:
            out.append(f"{hours} 小时前发布")
    pct = stats.get("percentile")
    if pct is not None and int(row.get("like_count") or 0) > 0:
        out.append(f"{PLATFORM_LABELS.get(row.get('platform'), '本站')}同类里热度前 {pct}%")
    return out[:3]


def summary(store) -> dict[str, Any]:
    total = store.count()
    platforms = store.platforms()
    newest = max((p["last_fetched_at"] or 0) for p in platforms) if platforms else 0
    top = sorted(platforms, key=lambda p: -p["count"])[:3]
    pieces = [f"库里共 {total} 条" if total else "还没有内容，先点右上角刷新"]
    if top:
        pieces.append("主要来自 " + "、".join(
            f"{PLATFORM_LABELS.get(p['platform'], p['platform'])} {p['count']} 条" for p in top))
    clusters = store.conn.execute(
        "SELECT cluster_id, COUNT(*) AS n FROM items WHERE cluster_id != '' "
        "GROUP BY cluster_id ORDER BY n DESC LIMIT 1").fetchone()
    if clusters and clusters["n"] >= 2:
        row = store.conn.execute(
            "SELECT title FROM items WHERE cluster_id = ? ORDER BY published_at DESC LIMIT 1",
            (clusters["cluster_id"],)).fetchone()
        if row:
            pieces.append(f"同一件事最多有 {clusters['n']} 个平台在讲：{row['title'][:24]}")
    return {"text": "；".join(pieces) + "。", "total": total, "platforms": platforms,
            "updated_at": newest, "offline": os.environ.get("ONEFEED_DEMO") == "1"}
