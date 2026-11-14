"""子进程 worker：在一个 fresh QuickJS context 里跑一次插件方法。

为什么是子进程：quickjs-py 的 `set_time_limit` 与宿主回调互斥
（设了 CPU 上限，JS 一旦调用 add_callable 就抛
`InternalError: Can not call into Python with a time limit set`），
所以 CPU 保护只能靠"主进程计时 + 强杀子进程"。代价是每次调用一次进程启动（~50ms），
换来的是死循环插件、内存炸弹都炸不到宿主。

协议：
    python -m plugin_runtime.worker <plugin_dir> <method> <args_json>
stdout 只输出一行 JSON：{"done":bool,"value":any,"error":str|null}
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import quickjs

from .capabilities import Capabilities
from .manifest import ManifestError, load_manifest

MEMORY_LIMIT = 64 * 1024 * 1024
DEADLINE_SEC = 25.0          # 小于宿主的 30s 硬超时，留出进程退出时间

SHIM = r"""
var __HOST_CALL__ = host_call;
function __call(cap, payload) {
  var req = Object.assign({ cap: cap }, payload || {});
  var res = JSON.parse(__HOST_CALL__(JSON.stringify(req)));
  if (!res.ok) { throw new Error(res.error || ("capability failed: " + cap)); }
  return res.data;
}

globalThis.__ctx__ = {
  http: {
    request: function (opts) {
      return Promise.resolve().then(function () {
        var r = __call("http", opts);
        r.json = function () { return JSON.parse(r.text); };
        return r;
      });
    }
  },
  cli: {
    run: function (opts) { return Promise.resolve().then(function () { return __call("cli", opts); }); }
  },
  browser: {
    capture: function (opts) { return Promise.resolve().then(function () { return __call("browser", opts); }); }
  },
  storage: {
    get: function (k) { return __call("storage", { op: "get", key: k }).value; },
    set: function (k, v) { return __call("storage", { op: "set", key: k, value: v }).value; },
    delete: function (k) { return __call("storage", { op: "delete", key: k }).value; },
    keys: function () { return __call("storage", { op: "keys" }).value; }
  },
  cache: {
    get: function (k) { return __call("cache", { op: "get", key: k }).value; },
    set: function (k, v, ttlSec) { return __call("cache", { op: "set", key: k, value: v, ttlSec: ttlSec }).value; }
  },
  settings: {
    get: function (k) { return __call("settings", { key: k }).value; }
  },
  util: {
    clamp: function (v) { return host_clamp(String(v === undefined || v === null ? "" : v)); }
  },
  log: {
    info: function (m) { host_log("[info] " + String(m)); },
    warn: function (m) { host_log("[warn] " + String(m)); },
    error: function (m) { host_log("[error] " + String(m)); }
  },
  env: { demo: __DEMO__ }
};
"""

RUNNER = r"""
function __errText(e) {
  if (!e) return "插件抛出空异常";
  var msg = (e && e.message) ? String(e.message) : String(e);
  var stack = (e && e.stack) ? String(e.stack) : "";
  if (stack.indexOf(msg) === 0) return stack;      // quickjs 的 stack 已带首行
  return msg + (stack ? "\n" + stack : "");
}
globalThis.__result__ = { done: false, value: null, error: null };
(function () {
  try {
    var fn = module.exports[__METHOD__];
    if (typeof fn !== "function") {
      __result__ = { done: true, value: null, error: "插件未实现 " + __METHOD__ };
      return;
    }
    Promise.resolve(fn(__ctx__, __ARGS__)).then(
      function (v) {
        try { JSON.stringify(v); __result__ = { done: true, value: v === undefined ? null : v, error: null }; }
        catch (e) { __result__ = { done: true, value: null, error: "返回值不可序列化: " + String(e) }; }
      },
      function (e) {
        __result__ = { done: true, value: null, error: __errText(e) };
      }
    );
  } catch (e) {
    __result__ = { done: true, value: null, error: __errText(e) };
  }
})();
"""


def _log(level: str, line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def run(plugin_dir: Path, method: str, args: dict, settings: dict, demo: bool) -> dict:
    manifest = load_manifest(plugin_dir)
    caps = Capabilities(manifest, settings=settings, demo=demo, logger=_log)

    ctx = quickjs.Context()
    ctx.set_memory_limit(MEMORY_LIMIT)
    ctx.add_callable("host_call", lambda raw: caps.handle(str(raw)))
    ctx.add_callable("host_clamp", lambda s: _safe_clamp(str(s)))
    ctx.add_callable("host_log", lambda msg: _log("info", str(msg)) or True)

    # CommonJS 垫片：插件按 MusicFree 的写法 module.exports = {...}
    ctx.eval("var module = { exports: {} }; var exports = module.exports;")
    ctx.eval(SHIM.replace("__DEMO__", "true" if demo else "false"))

    entry_path = manifest.entry_path
    ctx.eval(entry_path.read_text(encoding="utf-8"))

    ctx.eval(RUNNER
             .replace("__METHOD__", json.dumps(method))
             .replace("__ARGS__", json.dumps(args, ensure_ascii=False)))

    deadline = time.time() + DEADLINE_SEC
    while time.time() < deadline:
        ctx.execute_pending_job()
        if ctx.eval("__result__ && __result__.done"):
            break
        time.sleep(0.002)

    raw = ctx.eval("JSON.stringify(__result__)")
    result = json.loads(raw)
    if not result.get("done"):
        result = {"done": True, "value": None,
                  "error": "插件在 %.0fs 内没有返回（可能是死循环或未 resolve 的 Promise）" % DEADLINE_SEC}
    return result


def _safe_clamp(s: str) -> int:
    from .capabilities import clamp
    return clamp(s)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3:
        print(json.dumps({"done": True, "value": None,
                          "error": "用法: python -m plugin_runtime.worker <plugin_dir> <method> <args_json>"}))
        return 0

    plugin_dir = Path(argv[0])
    method = argv[1]
    try:
        args = json.loads(argv[2])
    except json.JSONDecodeError as exc:
        print(json.dumps({"done": True, "value": None, "error": f"args 不是 JSON: {exc}"}))
        return 0

    settings: dict = {}
    if os.environ.get("ONEFEED_SETTINGS"):
        try:
            settings = json.loads(os.environ["ONEFEED_SETTINGS"])
        except json.JSONDecodeError:
            settings = {}

    try:
        result = run(plugin_dir, method, args, settings, os.environ.get("ONEFEED_DEMO") == "1")
    except ManifestError as exc:
        result = {"done": True, "value": None, "error": f"清单错误: {exc}"}
    except Exception as exc:  # 插件崩溃/引擎错误
        result = {"done": True, "value": None, "error": f"{type(exc).__name__}: {exc}"}

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
