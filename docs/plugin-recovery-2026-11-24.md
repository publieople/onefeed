# 插件目录被删后的恢复（B 站，2026-11-24）

## 现象

- 11/23 10:22，`onefeed-plugins/plugins/bilibili` 发生了一次没有完成的插件目录替换：目录元数据还在，但 ACL / 枚举被拒。宿主读不到 `plugin.json`，报「插件读不动」。
- 11/24 用户手工删掉这个目录后，市场页仍然显示「哔哩哔哩 · 已安装」；点「刷新目录」没有变化；点「卸载」报「没有安装」，于是也装不回来。

## 根因：三处逻辑叠成一个死锁

1. `onefeed/service.py` 的 `sync_installed` 只往库里补记录，从不删除。目录被手工删掉后，`plugins` 表里那行还在。
2. `onefeed/market.py` 的 `uninstall` 先检查目录存在，不存在就直接报错，所以这行永远清不掉。
3. `web/src/pages/MarketPage.tsx` 只要 `installed=true` 就只渲染「卸载」，不渲染「安装」。

结果：市场页认为已安装 → 不显示安装；卸载又被目录不存在挡住 → 记录清不掉。

## 改动一：幽灵记录清理

- `onefeed/service.py`：`sync_installed(store, root, prune=False)`。`prune=True` 时，库里有、目录已经不存在的插件记录会被删掉；目录还在但这次没读动的保留，交给插件页继续报错。
- `onefeed/api.py`：`GET /api/plugins?refresh_market=true`（市场页「刷新目录」）会先调 `sync_installed(..., prune=True)`，再返回市场数据；卸载错误提示同步更新。
- `onefeed/market.py`：`uninstall` 改成幂等。目录不存在也删库记录，返回值带 `removed` 说明有没有真的删目录；文件 / 符号链接也能处理。
- `onefeed/app.py`：`create_app(store, plugins_dir=None)` 支持测试注入插件目录，避免测试碰真实插件。
- `tests/test_market_update.py`：新增「幽灵记录 → 刷新目录 → 重新安装 → 再删目录 → 幂等卸载」场景。

## 改动二：安装改成原子替换 + 回滚

参考 DSH 插件管理器的做法，不追求「目录 rename 本身绝对原子」，而是把可恢复状态先落盘：

1. **先 staging，后换入**。下载或复制到与插件根同级的隐藏目录 `.of-<plugin>-xxxx` 里，校验 `plugin.json` 和 `dir_hash` 之后才动正式目录。
2. **旧目录改名成 `previous` 备份**，新目录再 rename 到 target。任一步失败都能把备份移回来。
3. **换入后复核**。重新读 target 的 manifest、重算 `dir_hash`，确认换进来的就是期望版本。
4. **数据库最后写**。`upsert_plugin` 放在目录换好、复核通过之后；写库失败同样回滚目录，不会出现「目录是新的、库是旧的」。
5. **缓存失败不回滚**。安装已经成功时，复制市场缓存失败只返回 `cache_warning`，不影响插件可用。
6. **崩溃可恢复**。工作目录里的 `meta.json` 记录 plugin_id、target、action、preserve。服务启动时 `recover_installs()` 扫 `.of-*`：
   - target 不在：把 `previous` 移回去，库补登记；
   - target 已经是新版本、库还停在旧版本：按磁盘 manifest 补库，保留原来的启用状态；
   - 卸载已写库：直接清备份，不把插件目录恢复回来；
   - 回滚失败写过 `preserve`：启动时跳过，留给人处理。
7. **卸载也走同一套**：先把目录改名成 `previous`，库删成功后再清备份；删库失败就把目录移回，不再出现「目录没了、库里还显示已安装」。

对应实现：`onefeed/market.py` 的 `_work_dir`、`_write_meta`、`_keep_work`、`_rollback`、`_refresh_cache`、`recover_installs`；`onefeed/app.py` 在 `sync_installed` 之前调 `recover_installs`。

## 本次恢复操作

1. 重启 OneFeed 服务，加载新后端。
2. `GET /api/plugins?refresh_market=true`：已安装从 7 个变成 6 个，B 站幽灵记录被清掉，市场里 `bilibili.installed=false`。
3. `POST /api/plugins/bilibili/install`：从本地缓存 `.onefeed/market/plugins/bilibili-626d7b9e5253` 重装 0.5.0，sha256 `626d7b9e5253...`，目录恢复为 `index.js` + `plugin.json`。
4. `GET /api/plugins`：7 个插件全部登记，`errors` 为空。
5. `POST /api/refresh {platforms:["bilibili"], force:true}`：B 站这一轮 10 条、新增 9 条；`/api/health` 里 B 站从 `failed` 变成 `ok`，库内 B 站 279 条。

市场页复查：哔哩哔哩 0.5.0 · 已安装，顶栏无红色警示。

## 验证

- `uv run python tests/test_market_update.py`：81 项通过。
- 原子安装覆盖：staging→target rename 失败回滚、`upsert_plugin` 失败回滚、缓存复制失败仍登记、卸载删库失败移回目录。
- 崩溃恢复覆盖：换入前崩溃、换入后未写库、卸载已写库三种工作目录。
- `uv run python tests/run_all.py`：31 项全过。

## 边界

- 目录**存在但 ACL 坏掉**时，`prune` 会保守地保留记录；`uninstall` 仍可能因 `rmtree` 没有权限而失败。这种状态需要重启清句柄，或用管理员 `takeown` / `icacls` 处理，代码层不能绕过 Windows ACL。
- 原子替换只覆盖 onefeed 自己管理的插件目录。若进程在换入前被强杀，旧目录在隐藏的 `.of-*` 里；启动时恢复。若回滚本身失败，会写 `preserve: true` 并保留工作目录，不会自动删掉证据，需要人工处理。
- Windows 上目录 rename 仍可能被占用句柄挡住；这种失败会走回滚，不会留下半截 target。
