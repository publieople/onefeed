# Agent 搜不到时自己去抓一轮（2026-11-24）

> **已废止，仅留作过程记录。** 本文写的「运行器在 `search_items` 返回 0 时确定性自动抓」已在同日移除；现在的做法是模型自己判断并调用 `pull_feed`，每轮最多一次，停止回答会连采集一起停。现行方案见 [agent-control-2026-11-24.md](agent-control-2026-11-24.md)。

## 1. 问题

问 Agent 一个库里没有的词，它会老老实实回答「没找到」，即使七个平台的插件都装着、点一下刷新就能抓到。原因有两层：

- `onefeed/agent_runtime.py` 的 INSTRUCTIONS 第 9 条原本明写「用户没明说刷新，就不要调 refresh_feed：它会等确认、耽误几十秒」。
- `refresh_feed` 是 L3（会打外网），`actions.py` 的 `call()` 无条件要求用户确认，确认框一弹，对话就断了。

所以「主动去拉」不是模型愿不愿意的问题，是运行器根本没给它这条路。

## 2. 只改提示词不够

把第 9 条改成「搜不到就去刷新」能骗过一部分轮次，但剩下三种情况照样不成立：

1. 模型不一定会遵守，尤其它已经拿到「0 条」这个结论时，倾向于直接收尾。
2. 真调 `refresh_feed` 会弹确认，用户不在屏幕前就卡死到超时。
3. 一轮预算只有 120 秒、10 次工具调用，抓一轮七平台可能要几十秒，模型自己估不准该不该花。

结论：把「抓不抓」交给模型判断不可靠，做成运行器里的确定性兜底更合适——模型只负责搜索，搜空了由运行器补一手。

## 3. 做法

### 3.1 触发点

`_run_action` 里，`search_items` 返回 `count == 0` 时接管：

```python
if (name == "search_items" and isinstance(result, dict) and int(result.get("count") or 0) == 0):
    result = _auto_pull(deps, writer, args, result)
    ms = int((time.time() - started) * 1000)
```

只认 `search_items`。`get_item` / `similar_items` / `feed_stats` 搜空是正常结果，不该触发外网。

### 3.2 `_auto_pull`

- 已经抓过（`deps.auto_pulled`）、开关关着、没有 runner：原样返回，不动。
- 本轮剩余时间不足 30 秒（`AUTO_PULL_MIN_SECONDS`）：只发一条步骤「库里没有，但这轮没时间抓了」，说明原因而不是假装抓过。
- 平台：沿用这次搜索的 `query.platforms`（用户问「知乎上」就只抓知乎）；没限平台就是全部，冷却仍由 `RefreshRunner` 按平台判断。
- 等待预算：`max(10, min(50, 剩余 - 20))`，最多 50 秒（`AUTO_PULL_MAX_WAIT`），给后面的重查和收尾留时间。
- 调用 `actions.pull_feed(..., announce=False, should_stop=...) `：不重复发「刷新完成」的步骤，取消信号也能穿透到轮询里。
- 结果转成一句人话写进步骤：还在抓 / 新增 N 条 / 平台冷却中 / 没有新增 / 失败原因。
- 然后用同一组参数重查一次 `search_items`，把 `auto_pull={ok, added, note}` 挂在结果上；仍然 0 条时补一句「还是没搜到，换个说法或放宽条件。」

### 3.3 开关

`settings.DEFAULTS` 新增 `agent_auto_pull: true`，设置页「采集与排序」里一个 checkbox：「Agent 搜不到时自动抓一轮」。关掉后行为和以前一致。校验走和其他布尔项同一套（`validate` 里显式判 `isinstance(bool)`，未知键仍然拒收）。

### 3.4 提示词

第 9 条改成：自动抓一轮由运行器负责，模型不用调 `refresh_feed`；只有用户明说「刷新 / 更新 / 再抓一次」才调它（L3 会先问）。抓完还是 0 条就直说没有，别拿别的条目凑数。

## 4. 边界

| 情况 | 行为 |
| --- | --- |
| 一轮内第二次搜空 | 不再抓（`auto_pulled` 只置一次） |
| 平台在冷却期 | 照常走 `RefreshRunner`，冷却平台标 skipped，步骤里说明 |
| 整轮都在冷却 | `trigger` 返回 `phase="empty"`，步骤写「都在冷却，这轮没抓」，不重试 |
| 抓到一半被取消 | 抛 `Cancelled`，和正常取消一致 |
| 抓取超时 | 返回 `timed_out=True`，步骤写「还在抓」，先拿现有结果回答 |
| 开关关闭 | 完全退回旧行为，不额外花时间 |

## 5. 验证

- `tests/test_agent_runtime.py` 2b 段新增三个场景：首次搜空自动抓并重查到 1 条（`AutoRunner.calls == 1`、事件流里两条 `auto_pull` 步骤）、同一轮两次搜空只抓一次、开关关闭后不抓。该文件 106 项检查全过。
- `tests/test_refresh.py` 不受影响；`plugin_runtime/host.py` 的发现循环补了 `OSError` 容错，单个插件目录读不动只记一条 `errors`，不再让整轮启动/测试炸掉。
- 前端 `npm run build` 通过（见提交记录里的 bundle 体积）。
- 真机（2026-11-24 12:47，本机 `uv run python -m onefeed`，真实七平台）：
  - 问「拓扑绝缘体薄膜的外延生长最近有什么进展」，库里 1442 条命中 0；事件流按顺序出现 `search_items` → `auto_pull`「库里没有，先去各平台抓一轮」→ `auto_pull`「还在抓，先给你已经入库的部分」。
  - 50 秒等待预算到点时整轮还在跑，工具结果带回 `auto_pull: {ok: true, added: 19}`；随后后台把这一轮跑完，健康接口显示 1461 条（最终 1493），六平台 `last_fetched_at` 全部刷新。
  - 重查仍是 0 条（库里确实没有材料学内容），Agent 没有硬凑，先问了一句「要继续吗」，选「就到这」后回答「库里 1461 条全是知乎/B站/抖音等热榜流内容，没有科研材料学方向」。整轮 6 步 / 103 秒。
  - B 站这一轮没抓到：`onefeed-plugins\plugins\bilibili` 目录在 Windows 层不可读（连 `Get-Acl` 都拒绝访问，`last_fetched_at` 停在前一天），发现循环把它记进 `errors`：「插件目录读不动：…bilibili（[WinError 5] 拒绝访问）」。其余六个平台正常。
