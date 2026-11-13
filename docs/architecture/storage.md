# 存储架构

## 私有数据目录

```text
~/Library/Application Support/personal-creative-workspace/
├── content/
│   ├── sources/
│   │   ├── inbox/
│   │   ├── thoughts/
│   │   └── materials/
│   ├── knowledge/
│   │   ├── inbox/
│   │   ├── cards/
│   │   ├── maps/
│   │   └── indexes/
│   ├── outputs/
│   │   ├── articles/
│   │   └── reviews/
│   ├── assets/
│   ├── archive/
│   ├── trash/
│   ├── _templates/
│   ├── 知识首页.md
│   └── .obsidian/
├── documents/
│   └── resume-assets/              # 私有简历照片，随机文件名与 0600 权限
├── video-projects/
├── workspace.db
├── mobile.db
├── mobile.secret
├── working/
│   ├── agent-artifacts/           # 本地任务工作纸，0600，不是正式知识
│   ├── model-tasks/
│   ├── mobile-daily.json         # 可重建的手机看板快照，0600
│   ├── plugins/
│   │   ├── web/                   # 已安装的 Super Productivity Web 资源
│   │   ├── autoloop/              # 已安装的 Agent Autoloop 代码
│   │   ├── autoloop-data/         # Hub 日志数据库、规则和本机凭据
│   │   ├── results/               # 私有候选、问题和文字回答
│   │   ├── packages.json          # 固定版本和构建校验
│   │   ├── harness.json           # 可选的工作流执行后端配置
│   │   └── workflow-archive.json  # 可选的归档可见范围
│   └── wechat-push/intents/       # 24 小时待确认正文，不进入备份
└── backups/
```

## Markdown

Markdown 是随想、材料记录、周回顾、文章、知识卡和知识地图的唯一正文来源。解析器关闭原始 HTML，坏文件产生独立诊断，未知 Obsidian Properties 在工作台写回时必须保留。

工作台生成的 Obsidian 关联区块不计入正文、搜索、模型、回顾、公众号或视频输入。图片使用 `assets/文件名` 的可移植路径，网页端安全映射到受保护路由。

## SQLite

公开源码包含通用学习路线。职位、投递历史、候选人档案和简历均由仓库外的本机数据目录提供。

`workspace.db` 保存阶段行动、任务运行、求职、学习、搜索索引、模型账本、助手摘要/决策、收入账本、微信公众号推送元数据和 Obsidian 状态。Markdown 文件仍是权威正文；FTS5 索引保存为检索派生的标题、正文与选定元数据，可以重建。加密备份包含主库快照，因此也包含快照当时的索引文本。

`focus` v1–v3 保存独立待办和阶段、目标、交付物、最小行动、带手工状态的决策节点和周复盘。每日及每周重点均由作者手工选择，状态不会由日期自动推断。仅详情可见的目标不进入首页或助手投影。

`focus` v4 增加 `planner_slots` 与 `planner_activity`。排程按北京时间日期和半小时记录，与截止日期独立。活动只保存事项 ID、动作和时间，读取时套用当前可见性。

`agent_core` 子系统保存通用项目、任务、依赖、运行、步骤、脱敏工具调用和 Artifact 登记。Artifact 正文不进入数据库，而是以随机稳定 ID 存入 `working/agent-artifacts/`；数据库只保存逻辑文件名、SHA-256、摘要、状态和来源运行。第一版不把现有知识卡、文章、视频或简历复制为第二份 Artifact。

`agent_core` v2 在统一迁移中增加 `focus_action_tasks`，一项阶段行动至多关联一个本地任务；新任务及关联在同一写事务提交。首页、任务及运行总览根据来源目标的当前可见性过滤，任务及运行详情可沿引用返回行动。任务产物验收只写任务运行时状态，不写阶段行动或交付物。v3 增加 `daily_event_tasks`（独立待办关联）与 `agent_run_decisions`（每次运行的决策问题、选项与选定答案）；决策与运行暂停同事务提交，完整外发内容不存入日志。

Career v4 在原有 `resumes` 记录上增加简历工作室字段：`resume_kind`、`parent_id`、`job_id`、`structured_data`、`source_fingerprint`、`revision`、`template_key` 和 `is_primary`。Career v5 增加私有 `resume_assets` 与可选 `photo_asset_id`。已有记录只补默认值并保持 `legacy`，不会读取或改写原文件。主简历只有一个；岗位定制简历通过 `parent_id` 和 `job_id` 关联现有主简历与职位，并默认继承照片引用。`template_key` 只保存受控展示模板，不复制结构化简历；技术社招版的展示顺序也不会反向改写作者保存的区块顺序。每次结构化保存和照片变更使用 Revision 乐观锁，事实源指纹只用于提示待复核。

Career v7 为职位增加档位、投递日期与下一步。Career v8 在同一 `career` 统一迁移序列中增加只追加的 `job_resume_submissions`：关联岗位、来源简历、Revision、名称、目标岗位、结构化正文、模板、照片引用和记录时间。保存投递字段及阶段事件使用同一事务；只有进度实际变化才写事件。记录投递快照使用写事务读取源简历，以冻结一致版本；普通字段保存不创建快照。照片清理同时检查简历与投递快照引用，源简历更新或移除照片不破坏既有投递照片。来源简历引用可置空，快照正文仍保留；没有公开、搜索、助手或手机读取入口。升级前由统一迁移工具生成数据库备份，失败时事务回滚；降级代码前须显式恢复升级前备份，不能直接用旧代码打开 v8 数据库。


投递表自动保存沿用 Career v8，不新增迁移或表。局部字段更新在写事务锁内读取并校验当前记录，只修改白名单中的已提交字段，阶段变化与事件一起提交。新增表格行携带客户端 UUID，规范化后作为现有 `jobs.id` 的一部分；同一创建标识重试时返回已建立的记录，不再插入职位或初始阶段事件。此标识不含职位或私人正文，不建立额外状态表。

Career v6 增加 `learning_paths`、`learning_stages`、`learning_stage_references` 和 `learning_stage_capabilities`。四阶段路线使用稳定 ID 幂等初始化；状态、Commit、测试结果和私人复盘属于可变证据，重复启动不会重置。旧 `learning_references` 增加 `archived_at`，原四周路线只标记归档，不删除或覆盖原有证据。

国内照片版和无照片 ATS 版 PDF 都由本机 Playwright 从内存中的 Jinja2 打印 HTML 按需生成，响应使用 `no-store`，默认不持久化 PDF 或结构化导出副本。国内版会把私有照片转为 Data URL，ATS 版完全不读取照片；Chromium 不可用时保留对应打印 HTML 回退。

微信公众号 `wechat_publishing` 子系统只保存文章 ID/Revision、正文与封面哈希、标题/作者/摘要、图片数量、推送状态、脱敏错误码和草稿 `media_id`。完整导出 HTML 只进入 `working/wechat-push/intents/`，权限为 `0600`，最长保留 24 小时。AppID、AppSecret 和 Access Token 均不进入 SQLite。

收入由 `income` v3 迁移子系统管理。`income_sources` 固定保存数字产品、情报订阅、Micro-SaaS、广告与 CPS 四个方向；`income_entries` 保存手工录入的收入、费用和退款。Money Engine 表保存唯一首品、累计漏斗快照、五张固定职责卡，以及与收入记录关联的首单验证条件。`money_profiles`、`money_opportunities`、`money_evidence` 和 `money_retros` 分别保存本地画像、候选及冻结预测、公开证据摘要和实际复盘。旧 `bounty_income` 子系统保留不可变的 v1/v2 迁移历史，v3 只负责在升级前快照后清理已确认无有效记录的旧业务表；运行时代码不再依赖旧模型。

金额全部以人民币分保存。数据库只保存来源、金额、现金状态、可选普通备注、公开销售/证据入口和脱敏验证条件，不保存银行卡、支付账号、实名材料、付款凭证、买家身份或账户标识。证据 URL 只允许无账号信息的公开 HTTPS 地址，页面不会主动访问。收入数据不进入全局搜索或手机数据库。

`mobile.db` 独立保存设备、会话哈希和幂等回执，不与桌面或手机同步数据库文件。手机看板读取 `working/mobile-daily.json`，每天按北京时间核验日期。文件由桌面同步覆盖，不进入备份。

主库使用 `schema_migrations`，移动库使用 `mobile_schema_migrations`。升级前建立快照，迁移和版本登记位于同一事务；未知高版本必须拒绝启动，而不是尝试降级。

## 附件与临时数据

- 上传文档和图片使用随机存储名、真实签名校验和受保护下载路由。
- 简历照片位于 `documents/resume-assets/`，目录为 `0700`、文件为 `0600`；不进入静态目录、模型临时任务、搜索索引或手机数据库。
- 视频项目及交接包位于 `video-projects/`。
- 人工模型桥接正文位于 `working/model-tasks/`，七天后清理且不进入备份。
- 本地任务工作纸位于 `working/agent-artifacts/`，只有作者接受后才标记完成，不自动转成正式知识或创作内容。标准加密备份只纳入主库中的工作纸登记，不纳入 `working/` 正文；恢复到新环境后，产物登记不能替代丢失的工作纸文件。
- 微信草稿待确认正文位于 `working/wechat-push/intents/`，24 小时后清理且不进入备份。
- 微信 AppID 与 AppSecret 位于 macOS 钥匙串；Access Token 仅在运行进程内缓存。
- `.obsidian/`、API Key、设备会话和已有备份不进入新的加密内容备份。

## 权限与一致性

- 私有根目录权限为 `0700`，文件为 `0600`。
- 权威文件写入使用锁、临时文件、`fsync` 和原子替换。
- 附件与 Markdown 作为一次逻辑事务保存，正文失败时清理本次新增附件。
- FTS5 索引可删除和重建，不能反向覆盖权威内容。
- 测试和开发必须显式使用临时 `WORKSPACE_DATA_DIR`，不能读取作者默认数据根。

运行、迁移和备份步骤见 [运行维护](../operations/README.md)。
Obsidian Vault 内每个目录的用途和手动操作边界见 [私有知识库目录说明](private-vault-folders.md)。

## 桌面插件数据

| 数据 | 所在位置 | 恢复边界 |
|---|---|---|
| 日常待办、排期、计时 | Super Productivity 的 `http://localhost:8767` 浏览器源及其 IndexedDB | 使用 Super Productivity 自带的导出和导入，按实际使用的浏览器配置文件恢复。 |
| 调度规则、轮次、卡片和凭据 | `working/plugins/autoloop-data/`，包括 `rules.json` 与 `hub.db` | 单独保存 Autoloop 私有数据。保持其与工作台轮次关联的一致性。 |
| 工作项、审批和验收 | 主库的 `workflow_items`、`workflow_turns` | 随标准主库快照恢复。工作流 v1 增加这两张表，v2 增加私有文字回答文件的存在标记。 |
| 候选、问题和文字回答 | `working/plugins/results/` 下按轮次 ID 保存的 `*.json` 与 `*.answer.txt` | 单独备份并与主库及 Hub 日志配套恢复。文件权限为 `0600`。 |
| 归档范围与 Harness 选择 | `working/plugins/workflow-archive.json`、`working/plugins/harness.json` | 随插件数据备份。前者影响当前视图与旧事项的执行资格，后者决定工作流的执行后端。 |
| 安装包和校验 | `working/plugins/web/`、`autoloop/` 和 `packages.json` | 可按固定版本重新安装。 |
| 单轮 Harness 会话 | 隔离的本机临时目录 | 调用结束后清理，Harness 桌面端使用独立会话目录。持久产物以工作台文件为准。 |

主库、Autoloop 日志和结果文件通过工作项、轮次及卡片标识关联。只有主库快照时，可以恢复本地关联和审批状态，完整追溯还需要对应的 Hub 日志和结果文件。模型请求的输入边界和界面可见范围见[关键数据流](data-flows.md)。操作步骤见[桌面插件运维](../operations/workbench-plugins.md)。
