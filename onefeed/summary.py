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
from . import media as media_mod
from . import settings as settings_mod

POINT_MAX = 6
MATERIAL_MAX = 14000
# 一次最多带 3 张图：图文笔记的前三张通常就覆盖了主体，多带只是烧 token。
IMAGE_MAX = 3
IMAGE_DETAIL = "low"
# 推理型模型（deepseek-flash 之类）的思考也吃 max_tokens，1100 会被截成空正文。
MAX_SUMMARY_TOKENS = 2200

SYSTEM_PROMPT = """你在给用户总结一条他还没看的内容。只依据素材里出现过的信息，不补背景、不猜剧情、不编数字。

只输出 JSON，格式：
{"tldr":"一句话结论，30 字内，具体","points":[{"t":秒数或null,"text":"一个要点，45 字内"}],"caveat":"一句提醒，可为空"}

规则：
- points 2 到 6 条，按素材顺序，覆盖全片而不是只看开头。
- 素材里每行前面的 [mm:ss] 是时间点；某条要点对应哪一段，就把那一段的秒数填进 t，对应不上就填 null。
- 不要复述标题，不要写「本期视频」「UP 主」「作者认为」这类套话，直接说内容。
- 素材里没说的东西一律不写；素材太短就只给 1 到 2 条要点。
- caveat 只在素材明显不足时写一句，否则留空字符串。"""

# 流式用行协议而不是 JSON：JSON 得等括号闭合才能解析，行协议每写完一行就能显示。
STREAM_PROMPT = """你在给用户总结一条他还没看的内容。只依据素材里出现过的信息，不补背景、不猜剧情、不编数字。

按下面的行格式输出纯文本，不要 JSON、不要解释、不要空行：
TLDR: 一句话结论，30 字内，具体
- [mm:ss] 一个要点，45 字内
- 一个要点，没有时间点就不写方括号
注: 只在素材明显不足时写一句，否则不写这一行

规则：
- 要点 2 到 6 条，按素材顺序，覆盖全片而不是只看开头。
- 素材里每行前面的 [mm:ss] 是时间点；某条要点对应哪一段，就把那一段的时间填进方括号，对应不上就不写方括号。
- 不要复述标题，不要写「本期视频」「UP 主」「作者认为」这类套话，直接说内容。
- 素材里没说的东西一律不写；素材太短就只给 1 到 2 条要点。"""

# 素材档位：前端照着 basis 决定要不要把「注意」那行显示出来。
BASIS_TEXT = {
    "transcript": "完整字幕",
    "official": "平台总结",
    "desc": "标题与简介",
    "visual": "图片",
}

CAVEAT = {
    "transcript": "",
    "official": "这条没有字幕，上面的依据是平台自带总结。",
    "desc": "只拿到标题和简介，结论可能不完整。",
    "visual": "正文只有图片，结论来自图里看到的内容。",
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


def _refresh_detail(store: Any, host: Any, row: dict[str, Any]) -> dict[str, Any]:
    """重取一次详情：图片直链带签名，隔几小时就过期，旧地址取不到只能换新的。"""
    plugin_id = str(row.get("platform") or "")
    item_id = str(row.get("id") or "")
    if not item_id or host is None:
        return {}
    try:
        if not host.supports(plugin_id, "detail"):
            return {}
        fresh = host.detail(plugin_id, row)
    except Exception:  # noqa: BLE001 - 刷新失败就当没有图，不影响出总结
        return {}
    if not isinstance(fresh, dict) or not fresh:
        return {}
    try:
        store.save_detail(item_id, fresh)
    except Exception:  # noqa: BLE001
        pass
    return fresh


def _grab_images(item_id: str, plugin_id: str, row: dict[str, Any],
                 payload: dict[str, Any], slots: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    for index in range(min(slots, len(images))):
        got = media_mod.read_slot_image(item_id, f"img-{index}", payload, plugin_id)
        if got:
            out.append({"slot": f"img-{index}", "data": got[0], "mime": got[1]})
    if out:
        return out

    # 没有正文图（视频、文章）：用封面。封面可能不在 details 里，直接取条目上的 URL。
    media_payload = payload.get("media") if isinstance(payload.get("media"), dict) else {}
    cover = str(row.get("cover") or media_payload.get("poster") or "")
    if cover:
        got = media_mod.fetch_image(cover, referer=str(media_payload.get("referer") or ""),
                                    plugin_id=plugin_id, cache_key=item_id + ":cover")
        if got:
            out.append({"slot": "poster", "data": got[0], "mime": got[1]})
    return out


def _collect_images(store: Any, host: Any, row: dict[str, Any], payload: dict[str, Any],
                    slots: int = IMAGE_MAX) -> list[dict[str, Any]]:
    """挑不超过 IMAGE_MAX 张图并取回字节。

    图文取前几张（小红书正文常只有话题标签，内容全在图上）；视频取封面。
    取不到的图直接跳过——少一张图不该让整条总结失败；一张都取不到时
    重取一次详情换掉过期签名再试。
    """
    item_id = str(row.get("id") or "")
    plugin_id = str(row.get("platform") or "")
    if not item_id:
        return []
    out = _grab_images(item_id, plugin_id, row, payload, slots)
    if out:
        return out
    fresh = _refresh_detail(store, host, row)
    if not fresh:
        return []
    return _grab_images(item_id, plugin_id, row, fresh, slots)


def _image_blocks(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """图片 → OpenAI 兼容的 image_url 内容块。"""
    import base64

    blocks: list[dict[str, Any]] = []
    for image in images:
        data = image.get("data") or b""
        if not data:
            continue
        b64 = base64.b64encode(data).decode("ascii")
        blocks.append({"type": "image_url", "image_url": {
            "url": f"data:{image.get('mime') or 'image/jpeg'};base64,{b64}",
            "detail": IMAGE_DETAIL,
        }})
    return blocks


def _material(src: dict[str, Any], basis: str, images: int = 0) -> str:
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

    if images:
        parts.append(f"另有 {images} 张图片附在这条消息里，图里的文字和画面也算素材。")

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


def _detail_payload(store: Any, item_id: str) -> dict[str, Any]:
    """读详情缓存（一周内都算新鲜）：正文与图片都从这里拿。"""
    if not item_id:
        return {}
    try:
        cached = store.get_detail(item_id, max_age=7 * 86400)
    except Exception:  # noqa: BLE001 - 没有缓存就不带图，不该让总结失败
        return {}
    payload = (cached or {}).get("payload")
    return payload if isinstance(payload, dict) else {}


def _source(store: Any, host: Any, row: dict[str, Any]) -> tuple[
        dict[str, Any], str, int, str, str, list[dict[str, Any]]]:
    """取素材：插件交的优先，插件没认领就退回详情正文。

    返回 (src, basis, duration, material, plugin_note, images)。插件不给素材不算错误。
    """
    plugin_id = str(row.get("platform") or "")
    item_id = str(row.get("id") or "")
    payload = _detail_payload(store, item_id)
    src: dict[str, Any] | None = None
    plugin_note = ""
    try:
        # host 可能为 None（助手动作没有 runner）：没有宿主不算插件出错，直接走详情正文兜底
        src = host.summary_source(plugin_id, row) if (plugin_id and host is not None) else None
    except Exception as exc:  # noqa: BLE001 - 插件不给素材不算错误，换兜底
        plugin_note = str(exc)[:160]

    if src is None:
        part = payload.get("body") or {}
        body = _strip_html(str(part.get("value") or ""))[:4000]
        src = {"basis": "desc", "title": row.get("title"), "desc": row.get("text") or body,
               "duration": row.get("duration") or 0}

    basis = str(src.get("basis") or "").strip()
    if basis not in BASIS_TEXT:
        basis = "desc"
    try:
        duration = int(src.get("duration") or row.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0

    # 读图是要花钱的：设置里关掉就只走文本，其余逻辑不变。
    images: list[dict[str, Any]] = []
    if bool(settings_mod.load().get("vision_summary", True)):
        images = _collect_images(store, host, row, payload)
    if images and basis == "desc":
        # 正文只有标签（或干脆没正文）但拿到了图：这条其实是「图里说的」。
        body_len = len(str(src.get("desc") or "").strip())
        if body_len < 60:
            basis = "visual"

    material = _material(src, basis, len(images))
    if not material.strip() and not images:
        raise RuntimeError("这条内容没有能读的正文。")
    return src, basis, duration, material, plugin_note, images


def _messages(prompt: str, material: str, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """纯文本走字符串，带图走 content 数组（OpenAI 兼容的 image_url 块）。"""
    text = f"素材如下（{len(material)} 字）：\n\n{material}"
    blocks = _image_blocks(images)
    if not blocks:
        return [{"role": "system", "content": prompt},
                {"role": "user", "content": text}]
    return [{"role": "system", "content": prompt},
            {"role": "user", "content": [{"type": "text", "text": text}, *blocks]}]


def _payload(parsed: dict[str, Any], src: dict[str, Any], basis: str, duration: int,
             material_chars: int, engine: str, provider_name: str, model: str,
             started: float, images: int = 0) -> dict[str, Any]:
    """流式和非流式共用的收尾：章节从素材里取，其余原样带出。"""
    chapters = []
    raw_chapters = src.get("chapters")
    if isinstance(raw_chapters, list):
        for c in raw_chapters[:12]:
            if isinstance(c, dict) and c.get("title"):
                chapters.append({"t": int(float(c.get("t") or 0)), "title": str(c["title"])[:60]})
    return {
        "tldr": parsed.get("tldr") or "",
        "points": parsed.get("points") or [],
        "chapters": chapters,
        "caveat": parsed.get("caveat") or "",
        "basis": basis,
        "basis_text": BASIS_TEXT[basis],
        "duration": duration,
        "engine": engine,
        "provider": provider_name,
        "model": model,
        "source_chars": material_chars,
        "images": images,
        "ms": int((time.time() - started) * 1000),
        "generated_at": int(time.time()),
    }


def build(store: Any, host: Any, row: dict[str, Any]) -> dict[str, Any]:
    """给一条内容出总结。永不抛「模型挂了」——模型不行就退回摘原句。"""
    started = time.time()
    src, basis, duration, material, plugin_note, images = _source(store, host, row)

    parsed: dict[str, Any] | None = None
    engine, provider_name, model = "rules", "", ""
    images_used = len(images)
    attempts = [images, []] if images else [[]]
    for index, batch in enumerate(attempts):
        try:
            raw, provider = ai_mod.complete(_messages(SYSTEM_PROMPT, material, batch),
                                            max_tokens=MAX_SUMMARY_TOKENS, temperature=0.25)
            parsed = _parse(raw, duration)
            if parsed is None:
                raise ValueError("模型没给出可用 JSON")
            engine, provider_name, model = "llm", provider["name"], provider["model"]
            images_used = len(batch)
            break
        except Exception:  # noqa: BLE001 - 设置页之外没人该看到模型报错
            # 带图那次被拒（有的端点还不认 image_url）：摘掉图再试一次，别直接掉到摘原句
            if index + 1 < len(attempts):
                continue
            parsed = _rule_summary(src, basis, row)
            images_used = 0

    if not parsed.get("caveat"):
        parsed["caveat"] = CAVEAT.get(basis, "")
    if plugin_note and not parsed.get("caveat"):
        parsed["caveat"] = plugin_note

    return _payload(parsed, src, basis, duration, len(material),
                    engine, provider_name, model, started, images_used)


TLDR_LINE = re.compile(r"^\s*(?:tl;?dr|总览|一句话)\s*[:：]\s*(.+)$", re.I)
CAVEAT_LINE = re.compile(r"^\s*(?:注|注意|caveat|备注)\s*[:：]\s*(.+)$", re.I)
BULLET_LINE = re.compile(r"^\s*[-*·•]\s*(?:\[(\d{1,2}):(\d{2})\]\s*)?(.+?)\s*$")


def parse_lines(raw: str, duration: int) -> dict[str, Any] | None:
    """解析行协议。模型偶尔不听话（分段加空行、要点用圆点），所以按行宽容处理。"""
    tldr = ""
    caveat = ""
    points: list[dict[str, Any]] = []
    stray: list[str] = []
    limit = max(duration, 0) + 5
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        found = TLDR_LINE.match(line)
        if found and not tldr:
            tldr = found.group(1).strip()[:120]
            continue
        found = CAVEAT_LINE.match(line)
        if found:
            caveat = (caveat + " " + found.group(1).strip()).strip()[:160]
            continue
        found = BULLET_LINE.match(line)
        if found:
            if len(points) >= POINT_MAX:
                continue
            point: dict[str, Any] = {"text": found.group(3)[:160]}
            if found.group(1) is not None:
                at = int(found.group(1)) * 60 + int(found.group(2))
                if at <= limit:
                    point["t"] = at
            points.append(point)
            continue
        stray.append(line)
    if not tldr:
        # 模型忘了写 TLDR 前缀：拿第一句正文顶上，总比面板空着好
        if stray:
            tldr = stray[0].strip("*_# ")[:120]
        elif points:
            tldr = points[0]["text"][:120]
    if not tldr and not points:
        return None
    return {"tldr": tldr, "points": points, "caveat": caveat}


def stream_build(store: Any, host: Any, row: dict[str, Any]) -> Any:
    """流式总结：依次 yield meta → delta* → done（或 error）。

    落库的仍是和非流式同形的 dict，所以缓存、详情页、助手读总结这几条路径都不用改。
    """
    started = time.time()
    src, basis, duration, material, plugin_note, images = _source(store, host, row)

    yield {"type": "meta", "basis": basis, "basis_text": BASIS_TEXT[basis],
           "duration": duration, "source_chars": len(material), "images": len(images), "ms": 0}

    buf: list[str] = []
    engine, provider_name, model = "llm", "", ""
    images_used = len(images)
    # 三档机会：带图 → 带图但预算翻倍（推理模型把 token 全花在思维链上时）→ 摘掉图纯文本。
    # 端点不认 image_url 会直接报错，那种情况由下面 except 里的「没吐字就换下一档」接手。
    plans: list[tuple[list[dict[str, Any]], int]] = [(images, MAX_SUMMARY_TOKENS)]
    if images:
        plans.append((images, MAX_SUMMARY_TOKENS * 2))
        plans.append(([], MAX_SUMMARY_TOKENS))
    for index, (batch, budget) in enumerate(plans):
        buf = []
        thinking = False
        try:
            for kind, piece, provider in ai_mod.stream_complete(
                    _messages(STREAM_PROMPT, material, batch),
                    max_tokens=budget, temperature=0.25):
                provider_name, model = provider["name"], provider["model"]
                if kind == "thinking":
                    if not thinking:
                        thinking = True
                        yield {"type": "status", "phase": "thinking"}
                    continue
                buf.append(piece)
                yield {"type": "delta", "text": piece}
            if buf:
                images_used = len(batch)
                break
            # 流结束了却一个字正文都没有：换下一档再试
            if index + 1 < len(plans):
                continue
            fallback = _rule_summary(src, basis, row)
            yield {"type": "done", "fallback": True,
                   "summary": _payload(fallback, src, basis, duration, len(material),
                                       "rules", "", "", started)}
            return
        except Exception as exc:  # noqa: BLE001 - 模型中途挂掉，别把半截话丢了
            if index + 1 < len(plans) and not buf:
                continue
            note = (str(exc) or exc.__class__.__name__)[:160]
            partial = parse_lines("".join(buf), duration) if buf else None
            if partial is not None:
                partial["caveat"] = partial.get("caveat") or f"这次生成中途断了（{note}），上面是已经拿到的部分。"
                yield {"type": "done",
                       "summary": _payload(partial, src, basis, duration, len(material),
                                           "llm", provider_name, model, started,
                                           images_used if buf else 0)}
                return
            fallback = _rule_summary(src, basis, row)
            yield {"type": "done", "fallback": True,
                   "summary": _payload(fallback, src, basis, duration, len(material),
                                       "rules", "", "", started)}
            return

    parsed = parse_lines("".join(buf), duration)
    if parsed is None:
        # 模型没按格式吐字：退回摘原句，别给用户一个空白面板
        engine = "rules"
        parsed = _rule_summary(src, basis, row)
    if not parsed.get("caveat"):
        parsed["caveat"] = CAVEAT.get(basis, "")
    if plugin_note and not parsed.get("caveat"):
        parsed["caveat"] = plugin_note
    yield {"type": "done",
           "summary": _payload(parsed, src, basis, duration, len(material),
                               engine, provider_name, model, started, images_used)}

