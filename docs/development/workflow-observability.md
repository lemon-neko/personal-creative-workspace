# AI 工作流可观测性审计

2026-11-12。上游固定 Agent Autoloop v1.8.1，检出为 `e8748fd0c2aad4013e5996c3188535567070f24a`。协议与实现对应到上游 `kernel/http.ts`、`host/state.ts`、`host/runtime.ts` 与 `plugins/dsh/agent.ts`。[v1.8.1 协议](https://raw.githubusercontent.com/KKKKhazix/agent-autoloop/v1.8.1/docs/protocol.md)

桌面使用 FastAPI、Jinja、原生 JavaScript 和现有浅色样式。原控制中心已有快照、按序号重连的 SSE、事项分组、轮次详情与卡片操作。主要缺口是六节点混合统计与执行事实，事项详情默认跳到某一轮，且没有独立 Session 和基于 Fact 的回放。工作台通过服务端 Owner Key 读取 Hub，浏览器只访问同源投影。

| 上游读取 | 可证明的数据 | 展示边界 |
|---|---|---|
| `GET /v1/state` | `seq`、规则、来源计数、运行状态、Worker 心跳、当前卡片、近期卡片、定时器和分页游标 | 来源计数覆盖已配置来源；运行明细和近期卡片有窗口 |
| `GET /v1/runs/:id/why` | 原生 Fact 序号、时间、类型、相关事件和关系、规则版本、运行快照、回执与卡片变化 | 该轮的相关子集。序号跳跃是正常的，缺失的规则或开始事实单独提示 |
| `GET /v1/stream?after=seq` | 有序 Fact 和相应变更表 | SSE 发送安全失效提示，重新读取同源视图 |
| `POST /v1/cards/:id/answer`、`/resolve` | 上游接受的人工动作和后续关联 | 工作台模型卡仍先预览确认；续跑须有真实事件和新 Run |
| 本地审批与产物 | 工作台工作项、已审批轮次、受保护的产物文件 | 关联用 ID，`done` 表示轮次结束，验收状态以本地记录为准 |

清洗和去重缺少独立的运行 Fact。规则匹配和事项归并可通过派发时的 `runs.rule/grp/lane/rules_version` 与 `run_events` 证明。回执提交和解析发生在同一 `finish` 事务，解析没有独立时钟。历史中未记录的上下文准备、人工查看、续接过程均不可单独观测。

| 能力 | 上游 `plugins/dsh/agent.ts` | 工作台实际后端 |
|---|---|---|
| Session | 读取 headless JSONL 的 `sessionId`，支持按配置续接 | 隔离的 SDK 会话，每个获批轮次独立。无桌面可打开的会话 |
| 开始和结束 | 根据 `session` 与 `final` 判断 | Autoloop `started` / `finish`；SDK JSON-RPC 提供真实的 `turn/end` |
| 最终输出 | 读取 `final.text` | 校验后的草稿或问题保存到本地 |
| 用量与成本 | 累计 `step_end` Token | 读取本轮 DeepSeek 响应中的 Token。仅在原始回执上报成本时显示金额 |
| 流式消息 | 子进程输出 JSONL，Adapter 读取会话、用量和最终输出 | SDK 接收事件，工作台展示经校验的最终输出 |
| 工具、命令、文件 | 原生 Adapter 未向回执提供此类时间线 | 执行配置禁用工具，无命令或文件变化遥测 |
| 终端 stdout / stderr | stdout 承载 JSONL，stderr 尾部可供错误判断 | stdout 用于 JSON-RPC 协议，stderr 丢弃；未采集终端输出 |
| 隐藏思考与提示词 | 不属于控制面投影 | 不进入遥测或回放 |

## V3 展示模型

- `timeline` 由 Fact 中与轮次有关的记录投影成事件、派发、领取、回执和人工操作。每个条目带 `seq`、`at`、`factType`。同一序号可同时产生多条观测，例如一次回执附带卡片、定时器和发出的事件。
- `frames` 每个真实 Fact 序号一帧，`run` 保存该 Fact 中上游提供的安全状态字段。没有运行行的帧沿用此前最后一个已知快照。回放只读取页面中的投影，无需发送请求。序号跳跃不代表本轮日志丢失，无法证实的关键环节另有提示。
- 事项优先使用工作台持久关联 ID；原生事项用 `grp + lane`。无法确定关联时只展示原轮次。本地轮次列表来自工作台关联，原生列表按上游游标加载。历史每页读取最多八轮的可用 Fact，按真实序号合并，读取失败的轮次会单独标注。每轮也可单独检查 Trace。
- 私有 `working/plugins/results/<turn>.telemetry.json` 保存经允许的 SDK 观测时间与结果类别。采集失败不阻止模型产物保存。旧轮次没有历史 SDK 事件时保留「未采集」。页面同时展示 Autoloop 系统事实、Adapter 遥测和经校验的本地产物，并标注出处。

| 工作台入口 | 数据映射 |
|---|---|
| `/tasks`、`/workflow/control/state` | 当前状态 + 近期轮次 Fact 摘要，`activity` 最多 100 条。队列、当前卡片与定时器使用快照实数。 |
| `/workflow/control/stream` | 使用原有游标续传、去重、连接状态与按实体更新。浏览器不会接收 Owner Key。 |
| `/tasks/matters?item=…` 或 `?run=…` | 通过 `/workflow/control/matter` 查看事项、关联轮次、卡片、定时器和逐轮事实。游标加载更早的轮次日志。 |
| `/workflow/runs/:runId` | 分组时间线和终态回放。JSON 为允许列表后的 Fact 摘要。 |
| `/tasks/sessions/:runId` | 通过 Run 查找对应 Session 和本地轮次，显示生命周期、真实上报的用量、输出和已知续接。 |
| `/tasks/history`、`/tasks/rules` | 保留既有历史分页与筛选、原生规则查看和操作。 |

本地适配器采集两种可证实的事件。SDK 成功完成初始化时记录 `session.ready`，收到本轮 `turn/end` 时记录 `agent.finish`。时间戳是工作台观察到事件的时间。原始消息流、提示词、凭据和工具参数不持久化。当前 Workbench Harness 每轮启动新的临时会话，原生轮次的续接依据 `runs.resume/session` 展示。

截图用隔离的真实 Autoloop 与已安装的真实 Harness SDK 生成，模型服务为回环合成响应。该验收覆盖了本地协议、模型确认、卡片续跑、产物保存与浏览器界面。
