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
│   └── wechat-push/intents/       # 24 小时待确认正文，不进入备份
└── backups/
```

## Markdown

Markdown 是随想、材料记录、周回顾、文章、知识卡和知识地图的唯一正文来源。解析器关闭原始 HTML，坏文件产生独立诊断，未知 Obsidian Properties 在工作台写回时必须保留。

工作台生成的 Obsidian 关联区块不计入正文、搜索、模型、回顾、公众号或视频输入。图片使用 `assets/文件名` 的可移植路径，网页端安全映射到受保护路由。

## SQLite

`workspace.db` 保存求职、学习、搜索索引、模型账本、助手摘要/决策、收入账本、微信公众号推送元数据和 Obsidian 状态等结构化信息。它不保存 Markdown 正文副本。

`agent_core` 子系统保存通用项目、任务、依赖、运行、步骤、脱敏工具调用和 Artifact 登记。Artifact 正文不进入数据库，而是以随机稳定 ID 存入 `working/agent-artifacts/`；数据库只保存逻辑文件名、SHA-256、摘要、状态和来源运行。第一版不把现有知识卡、文章、视频或简历复制为第二份 Artifact。

Career v4 在原有 `resumes` 记录上增加简历工作室字段：`resume_kind`、`parent_id`、`job_id`、`structured_data`、`source_fingerprint`、`revision`、`template_key` 和 `is_primary`。Career v5 增加私有 `resume_assets` 与可选 `photo_asset_id`。已有记录只补默认值并保持 `legacy`，不会读取或改写原文件。主简历只有一个；岗位定制简历通过 `parent_id` 和 `job_id` 关联现有主简历与职位，并默认继承照片引用。每次结构化保存和照片变更使用 Revision 乐观锁，事实源指纹只用于提示待复核。

Career v6 增加 `learning_paths`、`learning_stages`、`learning_stage_references` 和 `learning_stage_capabilities`。四阶段路线使用稳定 ID 幂等初始化；状态、Commit、测试结果和私人复盘属于可变证据，重复启动不会重置。旧 `learning_references` 增加 `archived_at`，原四周路线只标记归档，不删除或覆盖原有证据。

国内照片版和无照片 ATS 版 PDF 都由本机 Playwright 从内存中的 Jinja2 打印 HTML 按需生成，响应使用 `no-store`，默认不持久化 PDF 或结构化导出副本。国内版会把私有照片转为 Data URL，ATS 版完全不读取照片；Chromium 不可用时保留对应打印 HTML 回退。

微信公众号 `wechat_publishing` 子系统只保存文章 ID/Revision、正文与封面哈希、标题/作者/摘要、图片数量、推送状态、脱敏错误码和草稿 `media_id`。完整导出 HTML 只进入 `working/wechat-push/intents/`，权限为 `0600`，最长保留 24 小时。AppID、AppSecret 和 Access Token 均不进入 SQLite。

收入由 `income` v3 迁移子系统管理。`income_sources` 固定保存数字产品、情报订阅、Micro-SaaS、广告与 CPS 四个方向；`income_entries` 保存手工录入的收入、费用和退款。Money Engine 表保存唯一首品、累计漏斗快照、五张固定职责卡，以及与收入记录关联的首单验证条件。`money_profiles`、`money_opportunities`、`money_evidence` 和 `money_retros` 分别保存本地画像、候选及冻结预测、公开证据摘要和实际复盘。旧 `bounty_income` 子系统保留不可变的 v1/v2 迁移历史，v3 只负责在升级前快照后清理已确认无有效记录的旧业务表；运行时代码不再依赖旧模型。

金额全部以人民币分保存。数据库只保存来源、金额、现金状态、可选普通备注、公开销售/证据入口和脱敏验证条件，不保存银行卡、支付账号、实名材料、付款凭证、买家身份或账户标识。证据 URL 只允许无账号信息的公开 HTTPS 地址，页面不会主动访问。收入数据不进入全局搜索或手机数据库。

`mobile.db` 独立保存设备、会话哈希和幂等回执，不与桌面或手机同步数据库文件。

主库使用 `schema_migrations`，移动库使用 `mobile_schema_migrations`。升级前建立快照，迁移和版本登记位于同一事务；未知高版本必须拒绝启动，而不是尝试降级。

## 附件与临时数据

- 上传文档和图片使用随机存储名、真实签名校验和受保护下载路由。
- 简历照片位于 `documents/resume-assets/`，目录为 `0700`、文件为 `0600`；不进入静态目录、模型临时任务、搜索索引或手机数据库。
- 视频项目及交接包位于 `video-projects/`。
- 人工模型桥接正文位于 `working/model-tasks/`，七天后清理且不进入备份。
- 本地任务工作纸位于 `working/agent-artifacts/`，只有作者接受后才标记完成，不自动转成正式知识或创作内容。
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
