"""T48 验收：AI 助手（意图解析 + 本地检索）。

跑法：python tests/test_ai.py [--verbose]

三件事必须成立：
1. 没有模型 key 时，规则解析照样能把「今天 B 站的 AI 视频」变成过滤条件；
2. 模型输出坏掉 / 超时 / 抛异常一律落回规则，不把错误抛给用户；
3. key 只进不出——GET /api/settings 里不能出现明文。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 必须在 import onefeed 之前：settings / state 目录都按 ONEFEED_HOME 解析
HOME = ROOT / ".onefeed" / "tmp" / "ai-test-home"
HOME.mkdir(parents=True, exist_ok=True)
for leftover in HOME.glob("settings.json"):
    leftover.unlink(missing_ok=True)
os.environ["ONEFEED_HOME"] = str(HOME)
os.environ.pop("ONEFEED_AI_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from onefeed import ai as ai_mod  # noqa: E402
from onefeed import settings as settings_mod  # noqa: E402
from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def seed(now: int) -> list[dict]:
    rows = [
        ("bilibili:ai1", "bilibili", "video", "五分钟讲懂大模型推理", "AI 大模型 入门", 0),
        ("bilibili:ai2", "bilibili", "video", "本地部署 DeepSeek 实录", "AI 部署 显存", 2),
        ("bilibili:game", "bilibili", "video", "今天聊聊装机", "显卡 装机", 6),
        ("xiaohongshu:ai1", "xiaohongshu", "images", "用 AI 做了一张海报", "AI 出图", 1),
        ("xiaohongshu:life", "xiaohongshu", "images", "周末去了天文馆", "上海 天文馆", 30),
        ("douyin:game", "douyin", "video", "挑战一天封神", "游戏 三角洲", 3),
        ("zhihu:ai1", "zhihu", "article", "深度学习怎么找 idea 发论文", "科研 idea AI", 4),
        ("zhihu-hot:hot1", "zhihu-hot", "list", "多地网约车司机称被特惠车逼疯", "网约车 特惠", 5),
    ]
    out = []
    for iid, platform, kind, title, text, hours in rows:
        out.append({
            "id": iid, "platform": platform, "kind": kind,
            "title": title, "text": text, "author": "作者",
            "cover": "", "url": "https://example.com/" + iid,
            "published_at": now - hours * 3600,
            "like": 100 + hours, "comment": 3, "share": 0, "view": 1000,
            "tags": [], "extra": {}, "fetched_at": now,
        })
    return out


def main() -> int:
    now = int(time.time())
    db = ROOT / ".onefeed" / "tmp" / "ai-test.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    store.upsert_items(seed(now))
    client = TestClient(create_app(store))

    # 1) 没配 key：rules 引擎
    st = client.get("/api/ai/status").json()
    check(st["engine"] == "rules" and st["configured"] is False, "没配 key 时走规则引擎")

    # 2) 一句话筛选：平台 + 类型 + 关键词
    resp = client.post("/api/ai/chat", json={"message": "只看今天 B 站的 AI 视频"}).json()
    check(resp["engine"] == "rules", "规则解析也标记引擎")
    check(resp["plan"]["platforms"] == ["bilibili"], "解析出 B 站")
    check(resp["plan"]["kinds"] == ["video"], "解析出视频")
    check("AI" in resp["plan"]["keyword"].upper(), "解析出关键词 AI")
    check(bool(resp["items"]) and all(i["platform"] == "bilibili" for i in resp["items"]),
          "结果只来自 B 站")
    check(all(i["kind"] == "video" for i in resp["items"]), "结果只有视频")
    check(bool(resp["reply"]) and bool(resp["understood"]), "有说法也有理解说明")
    check(isinstance(resp["suggestions"], list) and resp["suggestions"], "给后续建议")

    # 2b) 追问继承上一轮条件：只说「换成最热的」不该退化成全库乱搜
    follow = client.post("/api/ai/chat", json={
        "message": "换成最热的",
        "history": [{"role": "user", "text": "只看今天 B 站的 AI 视频"},
                    {"role": "assistant", "text": resp["reply"], "plan": resp["plan"]}],
    }).json()
    check(follow["plan"]["platforms"] == ["bilibili"], "追问沿用上一轮的平台")
    check(follow["plan"]["keyword"].upper() == "AI", "追问沿用上一轮的关键词")
    check(follow["plan"]["sort"] == "engagement", "追问只改排序")
    check(bool(follow["items"]), "追问之后不是空结果")

    # 3) 知乎不该被热榜吃掉：两个插件分开
    zh = client.post("/api/ai/chat", json={"message": "知乎上关于论文的内容"}).json()
    check(zh["plan"]["platforms"] == ["zhihu"], "知乎 -> zhihu 推荐流，不是知乎热榜")
    zh_hot = client.post("/api/ai/chat", json={"message": "知乎热榜"}).json()
    check(zh_hot["plan"]["platforms"] == ["zhihu-hot"], "知乎热榜 -> zhihu-hot")

    # 4) 刷一刷：mode=browse 且跨平台打散
    browse = client.post("/api/ai/chat", json={"message": "无聊，随便来点"}).json()
    check(browse["plan"]["mode"] == "browse", "「随便来点」识别成 browse")
    platforms = {i["platform"] for i in browse["items"]}
    check(len(platforms) >= 2, "browse 结果跨平台，不是一整屏同源")

    # 5) 换一批：exclude 生效
    first_ids = [i["id"] for i in browse["items"]]
    again = client.post("/api/ai/chat", json={"message": "无聊，随便来点", "exclude": first_ids}).json()
    check(not (set(first_ids) & {i["id"] for i in again["items"]}), "换一批不会重复上一批")

    # 6) 空问题 400
    empty = client.post("/api/ai/chat", json={"message": "  "})
    check(empty.status_code == 400 and empty.json()["error"]["code"] == "empty_message",
          "空问题给 400 而不是瞎猜")

    # 7) key 只进不出
    saved = client.put("/api/settings", json={"ai_api_key": "sk-test-only"}).json()
    check(saved["settings"].get("ai_api_key") == "", "PUT 回包不带明文 key")
    check(saved["ai"]["configured"] is True, "PUT 回包说已配置")
    raw = client.get("/api/settings")
    check("sk-test-only" not in raw.text, "GET /api/settings 不含明文 key")
    check(raw.json()["ai"]["engine"] == "llm", "配了 key 之后引擎变 llm")
    check(settings_mod.load().get("ai_api_key") == "sk-test-only", "磁盘上确实存了（宿主自己用）")

    # 8) 模型正常输出 -> 用模型的计划
    real_chat = ai_mod._chat
    try:
        ai_mod._chat = lambda messages: json.dumps({
            "mode": "find", "platforms": ["xiaohongshu"], "kinds": ["images"],
            "since": "week", "keyword": "海报", "sort": "engagement",
            "reply": "找小红书这周的海报图",
        })
        llm = client.post("/api/ai/chat", json={"message": "找点海报"}).json()
        check(llm["engine"] == "llm", "模型可用时用 llm 引擎")
        check(llm["plan"]["platforms"] == ["xiaohongshu"], "采纳模型给的平台")
        check(llm["reply"] == "找小红书这周的海报图", "采纳模型给的说法")
        check(all(i["platform"] == "xiaohongshu" for i in llm["items"]), "按模型计划检索")

        # 9) 模型抽风 -> 落回规则，不报错
        ai_mod._chat = lambda messages: "抱歉我不能回答这个"
        bad = client.post("/api/ai/chat", json={"message": "B 站的 AI 视频"}).json()
        check(bad["engine"] == "rules", "模型输出不是 JSON 时落回规则")
        check(bad["plan"]["platforms"] == ["bilibili"], "落回规则后解析仍然正确")

        def boom(messages):
            raise TimeoutError("slow")
        ai_mod._chat = boom
        slow = client.post("/api/ai/chat", json={"message": "B 站的 AI 视频"}).json()
        check(slow["engine"] == "rules", "模型超时也落回规则")
    finally:
        ai_mod._chat = real_chat
        settings_mod.save({"ai_api_key": ""})

    print(f"✅ test_ai.py  T48 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
