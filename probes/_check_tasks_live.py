"""真模型 + 真 HTTP 冒烟：让助手自己总结几条并导出 md（probes，手动跑）。

起服务：uv run python -m onefeed --port 8795 --no-browser
再跑：   $env:ONEFEED_PROBE_BASE="http://127.0.0.1:8795"; uv run python probes/_check_tasks_live.py
"""
from __future__ import annotations

import json
import os

import httpx

BASE = os.environ.get("ONEFEED_PROBE_BASE", "http://127.0.0.1:8795")
ASK = os.environ.get("ONEFEED_PROBE_ASK", "挑两条今天 B 站讲 AI 的视频，各写一句总结，然后导出成一份 md 简报")


def main() -> int:
    client = httpx.Client(trust_env=False, timeout=30)
    health = client.get(BASE + "/api/health", timeout=10).json()
    print("health", health.get("ok"), "items", health.get("items"))
    resp = client.post(BASE + "/api/agent/runs", json={"message": ASK, "limit": 8}, timeout=30)
    print("POST /agent/runs ->", resp.status_code, resp.text[:200])
    if resp.status_code != 202:
        return 1
    run_id = resp.json()["run_id"]
    print("ASK", ASK)
    with client.stream("GET", f"{BASE}/api/agent/runs/{run_id}/events", timeout=240) as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            print(f'{event["seq"]:>2} {event["kind"]:<12} {event["name"]:<16} '
                  f'{json.dumps(event["data"], ensure_ascii=False)[:180]}')
            if event["kind"] == "action":
                print("   TOKEN", event.get("undo_token", "")[:120])
            if event["kind"] == "done":
                data = event["data"]
                print("REPLY", data.get("reply"))
                print("ACTIONS", [a.get("name") for a in data.get("actions") or []])
                print("USAGE", data.get("usage"))
                break
            if event["kind"] == "error":
                print("ERROR", json.dumps(event["data"], ensure_ascii=False)[:400])
    listing = client.get(BASE + "/api/agent/runs", params={"events": 1, "limit": 3}, timeout=10).json()
    run = (listing.get("runs") or [{}])[0]
    exports = [e for e in run.get("events") or [] if e.get("kind") == "action"]
    print("RUN", run.get("status"), "events", len(run.get("events") or []), "actions", [e.get("name") for e in exports])
    for e in exports:
        if e.get("name") == "export_markdown":
            path = (e.get("data") or {}).get("path")
            print("EXPORT", path, "exists", os.path.exists(path or ""), "token", bool(e.get("undo_token")))
            if path and os.path.exists(path):
                text = open(path, encoding="utf-8").read()
                print("MD HEAD:", text.splitlines()[:4])
                print("MD LINES", len(text.splitlines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
