# 数据所有权与恢复边界

审计基线为 `6a8375e`。下列所有者是当前负责写入、解释和恢复数据的组件。两个 SQLite 文件、Vault、浏览器存储和 Hub 各自保留。目录和版本来自源码及临时目录初始化；审计未打开个人数据目录。

## 权威数据与投影

| 数据 | 权威位置与写入方 | 其他副本及边界 |
| --- | --- | --- |
| 当前待办、项目、排期与计时 | Super Productivity Web，浏览器配置文件中 `http://localhost:8767` 的 IndexedDB | 桌面桥接只读取已选任务 ID/标题和当天看板；主库工作项的标题是交接时快照。AI 验收不会改任务状态。 |
| 旧待办、阶段行动 | `workspace.db`，`FocusRepository` | 保留独立路由和写入能力。旧待办与 Super Productivity 各自拥有不同记录，无互相同步。 |
| 调度规则、事件、执行轮次、回执和卡片 | Autoloop v1.8.1，`working/plugins/autoloop-data/rules.json`、`hub.db` 及同目录配置；通过 Hub 协议读写 | 控制中心 SSE 游标和 Trace 缓存是投影。工作台的 run/card ID 用于引用；Hub 的完成回执与本地验收是两个状态。 |
| AI 工作项、外发批准和验收 | `workspace.db`，`WorkflowStore` | 轮次保存目标、批准指纹、派发标志及 Hub 引用。派发会使用稳定标识重新投递；执行结果不明时需要重新审批。 |
| AI 候选正文、私有文字回答及遥测 | `working/plugins/results/`，`WorkflowStore`，按轮次 ID 管理 | `*.json` 为候选，`*.answer.txt` 为回答，`*.telemetry.json` 为有限运行事件。Hub 只收到私有回答的引用，恢复答复需要文件与主库同时存在。 |
| 插件运行配置 | `working/plugins/`，安装器和运行管理；包括校验清单、启用标志、归档边界、Harness 选择和 Worker 领取标识 | 安装包可按版本重建；用户规则、归档标记和恢复关联需另存。进程锁属于运行态。 |
| 随想、材料、知识卡、地图、文章、回顾及回收站 | 仓库外的 `content/` Markdown/YAML，工作台和 Obsidian 编辑同一文件 | Revision、文件锁和原子替换保护写入。Obsidian SQLite 表保存集成元数据；导航、反链与 FTS 可重建。 |
| 求职、学习、阶段、收入、助手摘要、模型用量、旧任务及发布记录 | `workspace.db` 中对应 Repository | 搜索只复制允许的字段。简历投递快照是独立历史证据，保留记录时的正文与照片引用。 |
| 私有附件和业务文件 | `content/assets/`、`documents/`、`documents/resume-assets/`、`video-projects/` | Career 管附件及照片登记；视频模块管理项目与交接文件。数据库保存的是引用和元数据。 |
| 旧 Agent 产物与临时工作文件 | `working/agent-artifacts/`、`working/model-tasks/`、`working/wechat-push/` | 旧 Agent 主库只有登记。人工模型任务、待确认推送正文有各自保留期；钥匙串、环境变量或 Harness 本机凭据不进入标准备份。 |
| 移动设备、配对、会话与幂等回执 | `mobile.db` 与独立 `mobile.secret`，`MobileStore` | 手机自己的 IndexedDB 保存未上传草稿及已同步随想快照。未上传的草稿在手机端才有原件；收到回执后 Vault 为正文权威。 |
| 手机日常看板 | `working/mobile-daily.json`，桌面桥接派生的当天标题和时间 | 手机只读、按当天失效。与移动 SQLite 和手机离线随想是三条不同数据流。 |
| 全文检索 | `workspace.db` 的 FTS5、Revision 与元信息，`SearchRepository` | 扫描 Vault、Career 与视频记录生成；可清空重建，备份中的索引仍可能含选定正文。移动写入会尝试单条刷新。 |

## SQLite 表与迁移所有者

本表通过[隔离启动测试](../../tests/architecture/test_data_ownership.py)核对表名、唯一归属和注册版本。FTS 内部 shadow 表及 SQLite 内部表由 SQLite 管理。Career 内的四个业务组共用迁移标识和事务。

| 数据库 | 子系统 | 版本 | 当前所有者 | 逻辑表 |
| --- | --- | --- | --- | --- |
| `workspace.db` | `registry` | — | database | `schema_migrations` |
| `workspace.db` | `agent_core` | 3 | AgentCoreRepository | `workspace_projects`, `workspace_tasks`, `task_dependencies`, `agent_runs`, `artifacts`, `agent_steps`, `tool_calls`, `focus_action_tasks`, `daily_event_tasks`, `agent_run_decisions` |
| `workspace.db` | `assistant` | 1 | AssistantRepository | `assistant_conversations`, `assistant_turn_summaries`, `assistant_decisions` |
| `workspace.db` | `bounty_income` | 3 | IncomeRepository 历史兼容迁移 | 无现行表 |
| `workspace.db` | `career` | 8 | CareerRepository | `profile`, `documents`, `projects`, `resumes`, `resume_assets`, `jobs`, `job_events`, `job_resume_submissions`, `skills`, `job_skill_gaps`, `learning_tasks`, `learning_campaigns`, `quests`, `quest_learning_tasks`, `quest_evidence`, `career_radar_state`, `capability_domains`, `job_capabilities`, `capability_skills`, `learning_references`, `learning_reference_capabilities`, `learning_reference_tasks`, `learning_paths`, `learning_stages`, `learning_stage_references`, `learning_stage_capabilities` |
| `workspace.db` | `focus` | 4 | FocusRepository | `focus_cycles`, `focus_goals`, `focus_deliverables`, `focus_actions`, `focus_decisions`, `focus_checkins`, `daily_events`, `planner_slots`, `planner_activity` |
| `workspace.db` | `income` | 3 | IncomeRepository | `income_sources`, `income_entries`, `money_engine_products`, `product_metric_snapshots`, `revenue_validations`, `revenue_role_cards`, `money_profiles`, `money_opportunities`, `money_evidence`, `money_retros` |
| `workspace.db` | `model_gateway` | 1 | ModelUsageRepository | `model_usage`, `model_settings` |
| `workspace.db` | `obsidian` | 1 | ObsidianBridge | `obsidian_file_state`, `obsidian_integration_state` |
| `workspace.db` | `search` | 2 | SearchRepository | `workspace_search`, `workspace_search_state`, `workspace_search_meta` |
| `workspace.db` | `wechat_publishing` | 1 | WechatPushRepository | `wechat_draft_pushes` |
| `workspace.db` | `workflow` | 2 | WorkflowStore，可选子系统 | `workflow_items`, `workflow_turns` |
| `mobile.db` | `registry` | — | database | `mobile_schema_migrations` |
| `mobile.db` | `mobile_gateway` | 2 | MobileStore | `mobile_config`, `pairing_codes`, `mobile_devices`, `mobile_sessions`, `capture_idempotency`, `idea_edit_idempotency` |

## 现行跨域写入与迁移

- [旧 Agent 交接](../../app/agent_core.py)在同一写事务创建任务、写入 `focus_action_tasks` 或 `daily_event_tasks`，并调用 [Focus 的活动写入函数](../../app/focus.py)更新 `planner_activity`。AgentCore 还查询 Focus 行动、交付物、目标可见性。现有装配先建立 Focus 表；关联表的跨域外键与查询要求交接前两套表都已就绪。权限过滤和原子交接都是后续拆分的验收项。
- [助手确认路由](../../app/routers/assistant.py)经 Workspace 写随想或经 Career 创建学习任务，然后记录助手动作；动作记录有 `turn_id/action_id` 唯一性，但目标记录由另一写入创建。并发时第二个请求可能取得同一预留后继续写；目标写入与决策完结之间也有中断窗口。应以并发及中断注入验证幂等，保留人工确认。
- [移动写入](../../app/mobile.py)通过 MobileCaptureService 写 Vault、记录移动幂等状态，并尽力调用 SearchRepository 更新主库投影；投影失败允许后续对账。Obsidian 可绕过 HTTP 直接修改 Vault；桌面写入中间件无法收到该变化。
- [迁移框架](../../app/database.py)使用两个注册表按 subsystem 记录连续版本，开启 WAL、外键和 busy timeout。发现已有库需升级时先做 SQLite backup；在 `BEGIN IMMEDIATE` 内执行一个子系统的迁移和版本登记，出错回滚该事务，未知高版本拒绝。多个 Repository 在各自初始化时调用迁移，整个应用启动并非全库单事务。已有库回退依赖升级前快照；回滚单个子系统时仍需考虑快照会恢复整个文件及其他子系统的旧状态。Hub 与浏览器各走上游迁移。

## 备份与一致性

[标准加密备份](../../app/backup.py)逐项纳入主库的 SQLite backup、`content/`、`documents/`、`video-projects/`，跳过符号链接、`.obsidian/` 和内容锁。主库快照与文件遍历分时完成，恢复也按根目录逐项置换并保留回滚目录。它能验证清单和单库完整性，不能证明所有目录来自同一业务时间点。

| 恢复范围 | 当前能力 | 一致性检查 |
| --- | --- | --- |
| Vault、附件、主库 | 标准备份和隔离恢复演练；检索可重建 | 对照简历照片、知识来源和文章 Revision；生产恢复前暂停桌面写入、移动同步及 Obsidian 编辑。恢复路由只重建 Career 实例，其他服务和插件没有统一停机/重装配屏障。 |
| Hub、AI 轮次、产物 | 按[插件运维](../operations/workbench-plugins.md)单独备份 Hub 目录、results、归档和必要配置，与主库取同一停写窗口 | 隔离核对 run/card ID、未派发审批和结果文件。旧 Agent 正文另存；仅有主库时只保证可见部分元数据，须核对缺失或状态不明的工作项。 |
| Super Productivity | 通过相应浏览器配置文件使用上游导出/导入 | 打开同一浏览器源，核对待办、排期和计时。以任务 ID 关联 AI 工作项；历史标题可能与现任务不同。 |
| 移动 | 标准备份排除 `mobile.db` 和 `mobile.secret`；新环境按指南重新配对 | 停止移动同步，先处理设备未同步草稿；主库/Vault 恢复到旧时间点时，旧幂等回执可能仍引用恢复点之外的随想，检查后再续同步。 |
| 临时文件与凭据 | 手工模型草稿、短期微信推送正文、设备/模型密钥等按独立保留策略管理 | 恢复核验只输出计数、版本和校验和；需要恢复的第三方凭据通过原有安全配置重新建立。 |

恢复锚点会统计现场的 `mobile.db`，其清单范围大于标准加密包，比较时应限定同一备份范围。生产恢复的一致性、断点和凭据完整性应使用隔离演练确认，操作见[备份与恢复](../operations/backup-restore.md)。
