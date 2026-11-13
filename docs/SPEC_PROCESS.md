# 本仓库怎么用 spec 驱动开发

## 为什么

三个人、两周半、最后只有 8 小时现场开发。最贵的失败是「各写各的，最后拼不上」，
以及「演示时才发现某个功能没人做」。spec 的作用是**先把「做完」定义清楚**，减少口头共识。

## 四个文件，一条流水线

```
000-constitution.md     团队不可协商的规则（几乎不改）
        ↓
001-v1-core/spec.md     需求 + 验收标准 + 待定项（改一次要评审）
        ↓
001-v1-core/plan.md     技术方案：怎么实现（随 spec 变）
        ↓
001-v1-core/tasks.md    任务清单：谁做、做什么、做到什么程度算完
```

### 规则

1. **spec 是唯一事实来源。** 代码、PR、口头讨论跟 spec 冲突时，以 spec 为准；如果 spec 错了，先改 spec。
2. **新功能先加进 spec。** 任何人说「加个 XX 呗」，第一步是把 XX 写进 `spec.md` 的功能需求并给出验收标准，评审通过后才可能进代码。探索性脚本不受限（放 `probes/`，不进主链路）。
3. **改 spec 要评审。** 小改（补验收标准、修错别字）直接推；改范围（删功能、加平台、改产品形态）需要在群里说一句并让另外两人确认，评审记录写进 spec 的「变更记录」。
4. **每个 PR 关联 task id。** PR 描述第一行写 `Task: T07`。没有 task id 的 PR 说明 spec 没覆盖，先补。
5. **任务完成以验收标准为准。** 不看代码量，看 `tasks.md` 里那条的验收是否可复现。做完把 `[ ]` 改成 `[x]` 并补日期。

## 一次典型迭代

```
1. 在 spec.md 里加 FR-x（含验收标准 AC）
2. 在 plan.md 里补实现要点（数据流、接口、依赖）
3. 在 tasks.md 拆成 1~3 个可独立验证的任务，标依赖和 [P] 可并行
4. 开分支 feat/T07-xxx 写代码
5. 本地跑通验收 + `python pull_all.py` 冒烟
6. 开 PR（模板会要求填验收结果），另一人 review 后合并
7. tasks.md 打勾
```

## 分支与提交

- 分支：`feat/T07-dedup`、`fix/T12-sse-reconnect`、`spec/od-1-platforms`
- 提交：`feat(adapters): 抖音 adapter 支持评论抓取 (T04)`
- `main` 始终可运行：合并前必须 `python pull_all.py bili juejin` 能出数据（小红书未登录可跳过）

## 谁负责什么

| 角色 | 关注 | 对应 spec 区域 |
|---|---|---|
| 产品 / 路演 | 需求、验收标准、演示脚本 | spec.md、README |
| 前端 / 交互 | 卡片、动效、状态页 | plan.md 第 2 节、tasks T10–T15 |
| 后端 / 部署 | adapter、SQLite、SSE、DEMO 兜底 | plan.md 第 1/3 节、tasks T01–T09 |

## 别做的事

- 不把密钥、cookie、storage_state 提交进仓库（`.gitignore` 已挡大部分）
- 不在 `main` 上直接改功能代码
- 不为了「演示好看」写死的假数据 —— 假数据只能出现在 `fixtures/`，且必须能被 `ONEFEED_DEMO=1` 开关明确切换
