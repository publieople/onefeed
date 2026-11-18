"""真实模型 + 真实 HTTP 的 Agent 运行冒烟（probes，手动跑）。

起服务：uv run python -m onefeed --port 8791 --no-browser
再跑：   uv run python probes/_check_sse_live.py
"""
from __future__ import annotations

import json
import os

import httpx

BASE = os.environ.get("ONEFEED_PROBE_BASE", "http://127.0.0.1:8793")


def main() -> int:
    # 本机环境里有一个坏掉的代理变量，会把它拼进 localhost URL；探测一律绕开
    client = httpx.Client(trust_env=False, timeout=20)
    health = client.get(BASE + "/api/health", timeout=10).json()
    print("health", health.get("ok"), "items", health.get("items"))
    resp = client.post(BASE + "/api/agent/runs",
                       json={"message": "今天 B 站有哪些 AI 相关内容值得看的", "limit": 8},
                       timeout=30)
    print("POST /agent/runs ->", resp.status_code, resp.text[:220])
    if resp.status_code != 202:
        return 1
    run_id = resp.json()["run_id"]
    seen = []
    with client.stream("GET", f"{BASE}/api/agent/runs/{run_id}/events",
                       timeout=180) as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            seen.append(event["kind"])
            print(f'{event["seq"]:>2} {event["kind"]:<12} {event["name"]:<14} '
                  f'{json.dumps(event["data"], ensure_ascii=False)[:150]}')
            if event["kind"] == "done":
                data = event["data"]
                print("PLAN", json.dumps(data.get("plan"), ensure_ascii=False))
                print("ITEMS", len(data.get("items") or []))
                print("UNDERSTOOD", data.get("understood"))
                print("SUGGESTIONS", data.get("suggestions"))
                print("USAGE", data.get("usage"))
                break
            if event["kind"] == "error" and "fallback" in event["data"]:
                print("!! 模型失败，走兜底：", event["data"].get("message"))
    replay = client.get(f"{BASE}/api/agent/runs/{run_id}", timeout=10).json()
    print("replay status", replay["run"]["status"], "events", len(replay["events"]))
    print("kinds", seen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
