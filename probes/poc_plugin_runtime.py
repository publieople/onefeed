"""Plugin runtime PoC —— QuickJS 沙箱 + 能力注入 + 子进程硬超时。

验证 002-plugin-arch 的四个关键假设：
1. 插件用 module.exports 导出（MusicFree 写法），async pull 能在 QuickJS 里跑通；
2. 宿主注入的 ctx.http 能从 JS 侧调用，Promise 用 execute_pending_job 泵；
3. 插件拿不到文件/进程/网络裸接口，只能走宿主能力；
4. 插件是死循环时，靠「每插件一个子进程 + 主进程强杀」兜住，不影响宿主。

用法：
  python probes/poc_plugin_runtime.py                      # 跑 zhihu-hot，打印统一 Item
  python probes/poc_plugin_runtime.py --plugin dead-loop    # 演示超时击杀
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import quickjs

HERE = Path(__file__).parent
PLUGINS = HERE / "plugins"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


# ---------------------------------------------------------------- 能力层（宿主侧）
def http_request(payload: str) -> str:
    """ctx.http.request 的真实实现。返回 JSON 字符串，插件侧再包成对象。"""
    opts = json.loads(payload)
    url = opts.get("url", "")
    if url and opts.get("query"):
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(opts["query"])
    headers = {"User-Agent": UA, "Accept": "*/*"}
    headers.update(opts.get("headers") or {})
    req = urllib.request.Request(url, headers=headers, method=opts.get("method", "GET"))
    try:
        with urllib.request.urlopen(req, timeout=opts.get("timeoutMs", 15000) / 1000) as resp:
            return json.dumps({"status": resp.status, "text": resp.read().decode("utf-8", "replace")})
    except urllib.error.HTTPError as e:
        return json.dumps({"status": e.code, "text": e.read().decode("utf-8", "replace")})
    except Exception as e:
        return json.dumps({"status": 0, "error": f"{type(e).__name__}: {e}", "text": ""})


def clamp(value) -> int:
    """万/亿 字符串转 int，与 adapters/models.py 同规则。"""
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return 0
    s = value.strip().replace(",", "")
    mult = 1
    if s.endswith("万"):
        mult, s = 10_000, s[:-1]
    elif s.endswith("亿"):
        mult, s = 100_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


# ---------------------------------------------------------------- 沙箱（子进程内）
CTX_SHIM = """
globalThis.__ctx__ = {
  http: {
    request: async function (opts) {
      const r = JSON.parse(host_http(JSON.stringify(opts)));
      r.json = function () { return JSON.parse(r.text); };
      return r;
    }
  },
  util: { clamp: host_clamp },
  log: { info: host_log, warn: host_log, error: host_log },
  env: { demo: %s },
};
"""


def run_worker(plugin_dir: Path, method: str, args_json: str) -> dict:
    ctx = quickjs.Context()
    ctx.set_memory_limit(64 * 1024 * 1024)   # 内存上限
    ctx.add_callable("host_http", http_request)
    ctx.add_callable("host_clamp", clamp)
    ctx.add_callable("host_log", lambda msg: print("[plugin]", msg, file=sys.stderr) or True)

    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    entry = (plugin_dir / manifest.get("entry", "index.js")).read_text(encoding="utf-8")

    ctx.eval("var module = {exports:{}}; var exports = module.exports;")
    ctx.eval(entry)
    ctx.eval(CTX_SHIM % ("true" if os.environ.get("ONEFEED_DEMO") == "1" else "false"))

    ctx.eval(
        "globalThis.__result__ = {done:false, value:null, error:null};"
        "(function(){ try {"
        "  Promise.resolve(module.exports[%s].apply(null, [__ctx__, %s])).then("
        "    v => { __result__ = {done:true, value:v, error:null}; },"
        "    e => { __result__ = {done:true, value:null, error:String(e)}; });"
        "} catch (e) { __result__ = {done:true, value:null, error:String(e)}; } })();"
        % (json.dumps(method), args_json)
    )
    for _ in range(6000):
        ctx.execute_pending_job()
        if ctx.eval("__result__.done"):
            break
        time.sleep(0.002)
    return json.loads(ctx.eval("JSON.stringify(__result__)"))


# ---------------------------------------------------------------- 主进程（宿主侧）
def run_plugin(plugin_id: str, method: str, args: dict, timeout: float = 30) -> dict:
    plugin_dir = PLUGINS / plugin_id
    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", str(plugin_dir), method, json.dumps(args)]
    t0 = time.time()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s（子进程已强杀）", "elapsed": round(time.time() - t0, 2)}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or "").strip()[-400:], "elapsed": round(time.time() - t0, 2)}
    return {"ok": True, "manifest": manifest, "result": json.loads(proc.stdout), "elapsed": round(time.time() - t0, 2)}


def main(argv: list[str]) -> int:
    if len(argv) >= 5 and argv[1] == "--worker":
        plugin_dir, method, args_json = Path(argv[2]), argv[3], argv[4]
        print(json.dumps(run_worker(plugin_dir, method, args_json), ensure_ascii=False))
        return 0

    plugin_id = argv[2] if len(argv) > 2 and argv[1] == "--plugin" else "zhihu-hot"
    out = run_plugin(plugin_id, "pull", {"feedId": "hot", "limit": 5}, timeout=30)
    if not out["ok"]:
        print(f"[{plugin_id}] FAILED: {out['error']}  ({out['elapsed']}s)")
        return 1 if plugin_id != "dead-loop" else 0

    m = out["manifest"]
    res = out["result"]
    print(f"[{m['id']}] v{m['version']} caps={m['capabilities']} → {out['elapsed']}s")
    if res["error"]:
        print("plugin error:", res["error"])
        return 1
    items = res["value"]["items"]
    print(f"items: {len(items)}")
    for it in items:
        print(f"  - [{it['kind']}] {it['title'][:36]} | heat={it['stats'].get('view')} | {it['url'][:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
