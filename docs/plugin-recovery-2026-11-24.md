# 插件目录被删后的恢复（B 站，2026-11-24）

## 现象

- 11/23 10:22，`onefeed-plugins/plugins/bilibili` 发生了一次没有完成的插件目录替换：目录元数据还在，但 ACL / 枚举被拒。宿主读不到 `plugin.json`，报「插件读不动」。
- 11/24 用户手工删掉这个目录后，市场页仍然显示「哔哩哔哩 · 已安装」；点「刷新目录」没有变化；点「卸载」报「没有安装」，于是也装不回来。

## 根因：三处逻辑叠成一个死锁

1. `onefeed/service.py` 的 `sync_installed` 只往库里补记录，从不删除。目录被手工删掉后，`plugins` 表里那行还在。
2. `onefeed/market.py` 的 `uninstall` 先检查目录存在，不存在就直接报错，所以这行永远清不掉。
3. `web/src/pages/MarketPage.tsx` 只要 `installed=true` 就只渲染「卸载」，不渲染「安装」。

结果：市场页认为已安装 → 不显示安装；卸载又被目录不存在挡住 → 记录清不掉。

## 改动

- `onefeed/service.py`：`sync_installed(store, root, prune=False)`。`prune=True` 时，库里有、目录已经不存在的插件记录会被删掉；目录还在但这次没读动的保留，交给插件页继续报错。
- `onefeed/api.py`：`GET /api/plugins?refresh_market=true`（市场页「刷新目录」）会先调 `sync_installed(..., prune=True)`，再返回市场数据；卸载错误提示同步更新。
- `onefeed/market.py`：`uninstall` 改成幂等。目录不存在也删库记录，返回值带 `removed` 说明有没有真的删目录；文件 / 符号链接也能处理。
- `onefeed/app.py`：`create_app(store, plugins_dir=None)` 支持测试注入插件目录，避免测试碰真实插件。
- `tests/test_market_update.py`：新增「幽灵记录 → 刷新目录 → 重新安装 → 再删目录 → 幂等卸载」场景，市场测试 53 项。

## 本次恢复操作

1. 重启 OneFeed 服务，加载新后端。
2. `GET /api/plugins?refresh_market=true`：已安装从 7 个变成 6 个，B 站幽灵记录被清掉，市场里 `bilibili.installed=false`。
3. `POST /api/plugins/bilibili/install`：从本地缓存 `.onefeed/market/plugins/bilibili-626d7b9e5253` 重装 0.5.0，sha256 `626d7b9e5253...`，目录恢复为 `index.js` + `plugin.json`。
4. `GET /api/plugins`：7 个插件全部登记，`errors` 为空。
5. `POST /api/refresh {platforms:["bilibili"], force:true}`：B 站这一轮 10 条、新增 9 条；`/api/health` 里 B 站从 `failed` 变成 `ok`，库内 B 站 279 条。

市场页复查：哔哩哔哩 0.5.0 · 已安装，顶栏无红色警示。

## 验证

- `uv run python tests/test_market_update.py`：53 项通过。
- `uv run python tests/run_all.py`：31 项全过。

## 边界

- 目录**存在但 ACL 坏掉**时，`prune` 会保守地保留记录；`uninstall` 仍可能因 `rmtree` 没有权限而失败。这种状态需要重启清句柄，或用管理员 `takeown` / `icacls` 处理，代码层不能绕过 Windows ACL。
- `market.install` 仍是「删旧目录 → rename 新目录 → 复制缓存 → 写库」的顺序，不是原子替换；这次只修了死锁，没有改安装器。后续若要彻底避免 11/23 那种半截目录，应把旧目录先改名成 `.bak-时间戳`，新目录换上去，成功后再删备份，失败回滚，并把 `upsert_plugin` 提到缓存复制之前。
