"""AI 总结：把一条内容的素材压成「一句话 + 若干要点」。

素材由插件给（manifest 声明 summary、实现 summarySource）；插件没认领的，退回详情正文。
素材不够就短、就说清依据——不补背景、不猜剧情、不编数字。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from . import ai as ai_mod

POINT_MAX = 6
MATERIAL_MAX = 14000

SYSTEM_PROMPT = """你在给用户总结一条他还没看的内容。只依据素材里出现过的信息，不补背景、不猜剧情、不编数字。

只输出 JSON，格式：
{"tldr":"一句话结论，30 字内，具体","points":[{"t":秒数或null,"text":"一个要点，45 字内"}],"caveat":"一句提醒，可为空"}

规则：
- points 2 到 6 条，按素材顺序，覆盖全片而不是只看开头。
- 素材里每行前面的 [mm:ss] 是时间点；某条要点对应哪一段，就把那一段的秒数填进 t，对应不上就填 null。
- 不要复述标题，不要写「本期视频」「UP 主」「作者认为」这类套话，直接说内容。
- 素材里没说的东西一律不写；素材太短就只给 1 到 2 条要点。
- caveat 只在素材明显不足时写一句，否则留空字符串。"""

# 素材档位：前端照着 basis 决定要不要把「注意」那行显示出来。
BASIS_TEXT = {
    "transcript": "完整字幕",
    "official": "平台总结",
    "desc": "标题与简介",
}

CAVEAT = {
    "transcript": "",
    "official": "这条没有字幕，上面的依据是平台自带总结。",
    "desc": "只拿到标题和简介，结论可能不完整。",
}


def _mmss(sec: float) -> str:
    sec = max(0, int(sec or 0))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _field(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _timed_lines(src: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = src.get("transcript")
    lines = transcript.get("lines") if isinstance(transcript, dict) else None
    out: list[dict[str, Any]] = []
    if not isinstance(lines, list):
        return out
    for line in lines:
        if not isinstance(line, dict):
            continue
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        at: int | None = None
        if line.get("t") is not None:
            try:
                at = max(0, int(float(line["t"])))
            except (TypeError, ValueError):
                at = None
        out.append({"t": at, "text": text[:200]})
    return out


def _material(src: dict[str, Any], basis: str) -> str:
    """拼给模型看的素材。字幕带 [mm:ss]，其余按「标题 / 简介 / 官方总结 / 热评」的顺序。"""
    parts: list[str] = []
    title = str(src.get("title") or "").strip()
    if title:
        parts.append("标题：" + title[:120])
    desc = _strip_html(str(src.get("desc") or ""))
    if desc:
        parts.append("简介：" + desc[:800])
    official = _strip_html(str(src.get("official") or ""))
    if official:
        parts.append("平台自带总结：" + official[:1500])

    lines = _timed_lines(src)
    if lines:
        budget = max(2000, MATERIAL_MAX - sum(len(p) for p in parts))
        body: list[str] = []
        used = 0
        for line in lines:
            stamp = f"[{_mmss(line['t'])}] " if line["t"] is not None else ""
            row = stamp + line["text"]
            if used + len(row) > budget:
                break
            body.append(row)
            used += len(row) + 1
        parts.append("字幕（每行开头是时间点）：\n" + "\n".join(body))

    chapters = src.get("chapters")
    if isinstance(chapters, list) and chapters:
        rows = []
        for c in chapters[:30]:
            if isinstance(c, dict) and c.get("title"):
                rows.append(f"[{_mmss(c.get('t') or 0)}] {str(c['title'])[:60]}")
        if rows:
            parts.append("章节：\n" + "\n".join(rows))

    comments = src.get("comments")
    if basis == "desc" and isinstance(comments, list) and comments:
        rows = []
        for c in comments[:5]:
            if isinstance(c, dict) and c.get("text"):
                rows.append(f"· {str(c['text'])[:100]}（{int(c.get('like') or 0)} 赞）")
        if rows:
            parts.append("热评（只用来判断这条在讲什么）：\n" + "\n".join(rows))
    return "\n\n".join(parts)[:MATERIAL_MAX]


def _parse(raw: str, duration: int) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    tldr = str(obj.get("tldr") or "").strip()[:120]
    points: list[dict[str, Any]] = []
    raw_points = obj.get("points")
    if isinstance(raw_points, list):
        for p in raw_points[:POINT_MAX]:
            text, at = "", None
            if isinstance(p, dict):
                text = str(p.get("text") or "").strip()
                at = p.get("t")
            elif isinstance(p, str):
                text = p.strip()
            if not text:
                continue
            point: dict[str, Any] = {"text": text[:160]}
            limit = max(duration, 0) + 5
            if isinstance(at, bool):
                at = None
            if isinstance(at, (int, float)) and 0 <= at <= limit:
                point["t"] = int(at)
            elif isinstance(at, str):
                m = re.fullmatch(r"(\d{1,2}):(\d{2})", at.strip())
                if m and int(m.group(1)) * 60 + int(m.group(2)) <= limit:
                    point["t"] = int(m.group(1)) * 60 + int(m.group(2))
            points.append(point)
    if not tldr and not points:
        return None
    return {"tldr": tldr, "points": points,
            "caveat": str(obj.get("caveat") or "").strip()[:160]}


def _sentences(text: str, limit: int = 4) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"[。！？!?\n]+", text or ""):
        chunk = chunk.strip()
        if len(chunk) >= 6:
            out.append(chunk[:140])
        if len(out) >= limit:
            break
    return out


def _rule_summary(src: dict[str, Any], basis: str, row: Any) -> dict[str, Any]:
    """模型不可用时的退路：按素材顺序摘原句，不编东西。"""
    lines = _timed_lines(src)
    official = _strip_html(str(src.get("official") or ""))
    desc = _strip_html(str(src.get("desc") or ""))
    text = _strip_html(str(_field(row, "text") or ""))
    title = str(src.get("title") or _field(row, "title") or "").strip()

    points: list[dict[str, Any]] = []
    if lines:
        step = max(1, len(lines) // POINT_MAX)
        for i in range(0, len(lines), step):
            point: dict[str, Any] = {"text": lines[i]["text"][:140]}
            if lines[i]["t"] is not None:
                point["t"] = lines[i]["t"]
            points.append(point)
            if len(points) >= POINT_MAX:
                break
        tldr = official or lines[0]["text"][:100]
    else:
        base = official or desc or text
        for piece in _sentences(base):
            points.append({"text": piece})
        tldr = official[:100] if official else (title[:100] or (points[0]["text"] if points else ""))
    return {"tldr": tldr, "points": points,
            "caveat": "模型暂时不可用，这是按素材顺序摘的原句。"}


def build(store: Any, host: Any, row: dict[str, Any]) -> dict[str, Any]:
    """给一条内容出总结。永不抛「模型挂了」——模型不行就退回摘原句。"""
    started = time.time()
    plugin_id = str(row.get("platform") or "")
    item_id = str(row.get("id") or "")
    src: dict[str, Any] | None = None
    plugin_note = ""
    try:
        # host 可能为 None（助手动作没有 runner）：没有宿主不算插件出错，直接走详情正文兜底
        src = host.summary_source(plugin_id, row) if (plugin_id and host is not None) else None
    except Exception as exc:  # noqa: BLE001 - 插件不给素材不算错误，换兜底
        plugin_note = str(exc)[:160]

    if src is None:
        body = ""
        try:
            cached = store.get_detail(item_id, max_age=0)
            if cached and isinstance(cached.get("payload"), dict):
                part = cached["payload"].get("body") or {}
                body = _strip_html(str(part.get("value") or ""))[:4000]
        except Exception:  # noqa: BLE001 - 没有详情缓存也照样能出短总结
            body = ""
        src = {"basis": "desc", "title": row.get("title"), "desc": row.get("text") or body,
               "duration": row.get("duration") or 0}

    basis = str(src.get("basis") or "").strip()
    if basis not in BASIS_TEXT:
        basis = "desc"
    try:
        duration = int(src.get("duration") or row.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0

    material = _material(src, basis)
    if not material.strip():
        raise RuntimeError("这条内容没有能读的正文。")

    parsed: dict[str, Any] | None = None
    engine, provider_name, model = "rules", "", ""
    try:
        raw, provider = ai_mod.complete([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"素材如下（{len(material)} 字）：\n\n{material}"},
        ], max_tokens=1100, temperature=0.25)
        parsed = _parse(raw, duration)
        if parsed is None:
            raise ValueError("模型没给出可用 JSON")
        engine, provider_name, model = "llm", provider["name"], provider["model"]
    except Exception:  # noqa: BLE001 - 设置页之外没人该看到模型报错
        parsed = _rule_summary(src, basis, row)

    if not parsed.get("caveat"):
        parsed["caveat"] = CAVEAT.get(basis, "")
    if plugin_note and not parsed.get("caveat"):
        parsed["caveat"] = plugin_note

    chapters = []
    raw_chapters = src.get("chapters")
    if isinstance(raw_chapters, list):
        for c in raw_chapters[:12]:
            if isinstance(c, dict) and c.get("title"):
                chapters.append({"t": int(float(c.get("t") or 0)), "title": str(c["title"])[:60]})

    return {
        "tldr": parsed["tldr"],
        "points": parsed["points"],
        "chapters": chapters,
        "caveat": parsed["caveat"],
        "basis": basis,
        "basis_text": BASIS_TEXT[basis],
        "duration": duration,
        "engine": engine,
        "provider": provider_name,
        "model": model,
        "source_chars": len(material),
        "ms": int((time.time() - started) * 1000),
        "generated_at": int(time.time()),
    }
