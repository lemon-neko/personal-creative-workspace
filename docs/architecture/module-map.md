# 模块清单

以 Task 01 的模块清单为基线，补充已拆分的领域和插件运行时。依赖列为 AST 直接导入，省略共同的 `app.` 前缀。依赖于 FastAPI state 注入、子进程、HTTP、SQL 和浏览器消息的关系见[依赖图](dependency-map.md)。数据栏中「调用」表示经所有者接口触发，表归属见[数据所有权](data-ownership.md)。变更诱因列描述主要变化原因，未用 Git 次数估计变更频率。P0/P1/P2 定义见[审计报告](audit-report.md)。

| Module | Responsibility | Dependencies | Data Ownership | External Integration | Change Frequency（主要诱因） | Coupling | Refactor Priority |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [`app`](../../app/__init__.py) | Python 包标记 | — | — | — | 包入口调整 | 无业务依赖 | P2 |
| [`app.__main__`](../../app/__main__.py) | 桌面 CLI 调用 Uvicorn | — | — | Uvicorn | 启动参数 | 字符串指定 ASGI | P1 |
| [`app.agent_core`](../../app/agent_core.py) | 旧任务运行时兼容入口 | `agent_runtime`, `database` | 保留旧连接接口 | — | 转发至领域服务 | AppContainer 装配依赖 | — |
| [`app.agent_runtime`](agent-runtime.md) | 项目、任务、运行、产物与执行策略 | SQLite、Focus、Search、ModelGateway 经端口和适配器 | 旧 Agent 表与私有工作纸 | Gateway 经适配器 | 状态转换、交接、人工验收 | 与 Focus 共用交接事务 | — |
| [`app.asgi`](../../app/asgi.py) | 桌面生产 ASGI 装配 | `main` | 运行目录初始化 | Uvicorn | 装配入口调整 | 导入即调用工厂，有预期副作用 | P0 |
| [`app.assistant`](../../app/assistant.py) | 白名单上下文、模型结果验证、对话摘要和决策 | `career`, `content`, `database`, `focus`, `knowledge_quality`, `knowledge_store`, `workspace` | 助手表 | — | 上下文、建议和隐私规则 | 读取 Career、Focus、Vault；Gateway 反向引用验证 | P1 |
| [`app.atomic`](../../app/atomic.py) | 文件锁和原子替换 | — | 锁文件 | 文件系统、fcntl | 并发与持久性 | Unix 实现，多域共用 | P2 |
| [`app.backup`](../../app/backup.py) | AES 归档、清单核验和分步恢复 | — | 备份包与回滚目录 | pyzipper、SQLite backup | 备份范围与恢复 | 恢复跨文件，缺少应用级停写屏障 | P1 |
| [`app.career`](career-domain.md) | 档案、文档、证据、简历、投递、学习事务 | `career_radar`, `database`, `resume_assets`, `resume_studio` | Career 子系统和私有文档 | SQLite、文件系统 | 招聘流程、文档、课程、简历结构 | 共享 Repository、SQL 与快照外键 | P1 |
| [`app.career_radar`](../../app/career_radar.py) | 通用课程、能力与参考项目种子 | — | 源码中的课程初值 | 开源仓库链接 | 课程与能力更新 | 由 Career seed 调用 | P2 |
| [`app.content`](../../app/content.py) | 解析、加载、渲染 Markdown 和改写链接 | `knowledge_store` | ContentItem 解析表示 | Markdown-it、PyYAML | 内容语法、链接兼容 | 函数内反向导入 KnowledgeStore | P1 |
| [`app.database`](../../app/database.py) | SQLite 连接、版本注册、快照和事务迁移 | — | 两份迁移注册表、升级前快照 | SQLite WAL/backup | 迁移与权限 | Repository 构造时隐式触发迁移 | P0 |
| [`app.deepseek_harness`](../../app/deepseek_harness.py) | stdio SDK、单次模型代理和遥测 | `llm` | 进程内会话与遥测 | dsh、DeepSeek、HTTPX | SDK 协议、凭据、退出 | 与具体 LLM 客户端耦合，Worker 识别具体类型 | P1 |
| [`app.focus`](../../app/focus.py) | 阶段、目标、行动、旧待办与排期 | `database`, `workspace` | Focus 子系统 | SQLite | 状态、排期和可见性 | 活动 SQL 被旧 Agent 事务复用 | P1 |
| [`app.income`](../../app/income.py) | 账本、首品验证、机会验证与复盘 | `database` | Income 与历史赏金迁移 | SQLite | 指标、证据、归档和复盘 | 共享 Repository 同时承载金额规则和流程门控 | P1 |
| [`app.install_plugins`](../../app/install_plugins.py) | 安装、刷新 Web 和启用标记 | `plugin_packages`, `plugin_paths`, `workflow_hub` | 安装包、清单、配置、凭据 | Git、tar、Node CLI | 固定版本和安装方式 | 更新使用临时目录与回退 | — |
| [`app.knowledge`](../../app/knowledge.py) | 来源筛选、检索上下文与知识关系视图 | `content`, `workspace` | 派生图和材料选择 | — | 关系与上下文选择 | 直接依赖 Vault 内容生命周期 | P1 |
| [`app.knowledge_quality`](../../app/knowledge_quality.py) | 内容质量、链接与缺失项检查 | `content`, `knowledge_store`, `obsidian` | 派生诊断 | — | 诊断规则 | 引入 Obsidian 实现 | P2 |
| [`app.knowledge_store`](../../app/knowledge_store.py) | 知识卡/地图解析、版本、写入和复核 | `atomic`, `content`, `workspace` | 知识 Markdown | 文件系统、PyYAML | 分类、引用和 Revision | 与通用内容/Workspace 循环 | P1 |
| [`app.library`](../../app/library.py) | 材料文件创建、读取与状态更新 | `workspace` | 材料 Markdown | 文件系统 | 材料状态与字段 | 复用 Workspace 写入规则 | P2 |
| [`app.llm`](../../app/llm.py) | 通用模型配置、请求和结构化输出 | `content`, `knowledge` | 进程内模型配置 | OpenAI-compatible HTTP | 模型协议、响应校验 | Provider 适配器认识内容及知识 DTO | P1 |
| [`app.main`](../../app/main.py) | 桌面工厂、装配、迁移、生命周期和搜索中间件 | `agent_core`, `assistant`, `career`, `content`, `database`, `focus`, `income`, `knowledge_store`, `library`, `llm`, `mobile`, `model_gateway`, `obsidian`, `plugin_runtime`, `plugins`, `privacy`, `search`, `video`, `web`, `wechat`, `workflow`, `workspace` | FastAPI state、运行目录 | FastAPI | 新领域接入、启动、索引 | 装配和业务编排混合 | P0 |
| [`app.migrate_private_data`](../../app/migrate_private_data.py) | 旧数据搬迁预演和安全复制 | `privacy` | 迁移计划及目标私有文件 | 文件系统 | 旧路径兼容 | 运行工具显式初始化目标 | P2 |
| [`app.migrate_vault`](../../app/migrate_vault.py) | Vault 结构迁移 CLI | `privacy`, `vault` | 迁移结果 | 文件系统 | Vault 演进 | CLI 复用 Vault 迁移逻辑 | P2 |
| [`app.mobile`](../../app/mobile.py) | 移动设备仓储、配对、会话和捕获编辑用例 | `atomic`, `content`, `database`, `search`, `workspace` | 移动表、mobile.secret、写入 Vault | SQLite、文件系统 | 鉴权、离线冲突与幂等 | 用例直接调用 Workspace 和 Search | P1 |
| [`app.mobile_asgi`](../../app/mobile_asgi.py) | 移动生产 ASGI 装配 | `mobile_main` | 运行目录初始化 | Uvicorn | 启动入口 | 导入调用移动工厂 | P1 |
| [`app.mobile_daily`](../../app/mobile_daily.py) | 每日快照校验、写入和读取 | `atomic`, `database` | mobile-daily.json | Pydantic、文件系统 | 手机看板字段 | 桌面生产、移动消费；复用 database 时区 | P2 |
| [`app.mobile_launcher`](../../app/mobile_launcher.py) | 读取移动配置、检查代理并启动服务 | `mobile`, `privacy` | — | Tailscale CLI、Uvicorn | 代理与启动配置 | 依赖 MobileStore 配置 | P1 |
| [`app.mobile_main`](../../app/mobile_main.py) | 移动工厂、PWA 路由与安全中间件 | `mobile`, `mobile_daily`, `privacy`, `search` | 移动应用 state | FastAPI、Tailnet 代理 | API、Cookie、PWA | 装配与路由、会话、模板同文件 | P1 |
| [`app.model_gateway`](../../app/model_gateway.py) | 提供方策略、模型用量、人工桥接与调用 | `assistant`, `database`, `deepseek_harness`, `llm`, `resume_studio`, `workspace` | 模型 SQLite、手工任务文件 | 模型 HTTP、Harness | 任务策略、成本、解析器 | 引用助手与简历校验；具体 Provider 识别 | P1 |
| [`app.obsidian`](../../app/obsidian.py) | Vault 扫描、链接、导入、迁移与回滚 | `atomic`, `content`, `database`, `knowledge_store`, `workspace` | Vault 集成状态及派生链接 | 本机 Obsidian、文件系统 | 同步、Revision、权限 | 直接组合多个知识/内容实现 | P1 |
| [`app.planner`](../../app/planner.py) | 旧排期视图辅助和日期计算 | `focus`, `workspace` | 派生月历和时间段 | — | 展示和排期规则 | 读取 Focus DTO | P2 |
| [`app.plugin_runtime`](../../app/plugin_runtime.py) | 插件独占锁与生命周期 | `daily_plugin`, `autoloop_plugin`, `process_supervisor` | 进程锁与运行状态 | 本机文件锁 | 启停、诊断与清理 | [监督和适配器](plugin-runtime.md) | — |
| [`app.plugin_web`](../../app/plugin_web.py) | 独立源只读静态 Web 服务及 CSP | `daily_plugin`, `plugin_paths`, `privacy` | — | Uvicorn、静态文件 | Web 包安全和端口 | 响应 CSP 与签名挑战 | P1 |
| [`app.plugins`](../../app/plugins.py) | 内置 PluginSpec、导航与依赖验证 | `plugin_paths` | 静态元数据 | — | 插件查询和验证 | Router 由 Bootstrap 装配 | — |
| [`app.privacy`](../../app/privacy.py) | 本机访问、CSRF、安全头和数据目录 | `plugin_paths` | CSRF Cookie、目录约束 | FastAPI/Starlette | 隐私与访问政策 | CSP 按请求的 Web 探针结果开放 iframe 源 | — |
| [`app.publishing`](../../app/publishing.py) | 公众号排版生成、私有发布包及复制 | `content`, `publishing_preprocess`, `publishing_theme`, `workspace` | 导出 HTML 与私有文件 | Markdown 渲染 | 平台格式和内容政策 | 复用 Content/Workspace | P2 |
| [`app.publishing_preprocess`](../../app/publishing_preprocess.py) | 清理 Markdown 链接与图片、规划版面 | — | 派生文稿及诊断 | — | 排版和清理规则 | 纯转换可独立测试 | P2 |
| [`app.publishing_theme`](../../app/publishing_theme.py) | 公众号主题、Markdown 转版式 | `publishing_preprocess` | 派生 HTML | Markdown 渲染 | 样式与兼容 | 复用发布预处理 | P2 |
| [`app.recovery`](../../app/recovery.py) | 恢复锚点与隔离演练 CLI | `backup`, `database`, `privacy` | 清单、隔离副本 | SQLite、文件系统 | 恢复验收、对账 | 锚点计入 mobile.db，标准备份排除 | P1 |
| [`app.resume_assets`](../../app/resume_assets.py) | 照片二进制校验、存储支持 | — | 简历照片 | 文件系统 | 格式、尺寸、校验 | 被 Career/导入/路由共同使用 | P2 |
| [`app.resume_docx`](../../app/resume_docx.py) | 本地 DOCX 文本与照片提取及结构映射 | `resume_assets`, `resume_studio` | 派生导入候选 | ZIP/XML | Word 兼容、映射 | 依赖简历结构和照片校验 | P1 |
| [`app.resume_import`](../../app/resume_import.py) | 显式导入 CLI 与确认写入 | `career`, `privacy`, `resume_docx`, `resume_studio` | 候选、原文件登记和主简历 | 文件系统 | 导入流程与版本 | 同时依赖 CLI 配置、Repository、文档提取 | P1 |
| [`app.resume_pdf`](../../app/resume_pdf.py) | Chromium 打印受控简历 HTML | — | 派生 PDF | Playwright Chromium | 模板输出和浏览器兼容 | 导出适配边界已较清晰 | P2 |
| [`app.resume_studio`](../../app/resume_studio.py) | 结构化简历、校验、本地匹配与候选合并 | — | 简历 DTO 与派生建议 | — | 简历规则和候选字段 | 被持久层、模型网关和 HTTP 共用 | P1 |
| [`app.routers`](../../app/routers/__init__.py) | HTTP 包标记 | — | — | — | 路由组织 | 无业务依赖 | P2 |
| [`app.routers.agent_core`](../../app/routers/agent_core.py) | 旧任务/运行/产物和模型授权 HTTP | `agent_core`, `agent_runtime`, `web` | 调用运行时服务 | FastAPI | 旧 Agent 操作 | HTTP 层委托预览和执行 | P1 |
| [`app.routers.assistant`](../../app/routers/assistant.py) | 助手表单、预览、确认与跨域动作 HTTP | `assistant`, `model_gateway`, `web`, `workspace` | 调用助手、Vault 和学习写入 | FastAPI | 来源白名单与人工确认 | 跨模块编排在 HTTP 层 | P1 |
| [`app.routers.career_learning`](../../app/routers/career_learning.py) | 档案、附件、投递、技能与学习 HTTP | `career`, `model_gateway`, `web` | 调用 Career 写入 | FastAPI | 投递、技能、学习变更 | 多类用例同文件，直接组合 Gateway 与 Repository | P1 |
| [`app.routers.creation`](../../app/routers/creation.py) | 文章、排版、创作模型与视频 HTTP | `content`, `llm`, `model_gateway`, `obsidian`, `publishing`, `publishing_theme`, `video`, `web`, `wechat`, `workspace` | 调用 Vault、视频和派生检索写入 | FastAPI | 创作流程与导出 | 写入后直接刷新部分索引 | P1 |
| [`app.routers.daily`](../../app/routers/daily.py) | Super Productivity 容器、旧入口和手机快照 HTTP | `mobile_daily`, `plugin_paths`, `routers.workspace_content`, `web` | 写手机快照 | FastAPI、Web 健康探测 | iframe 和移动投影 | 依赖 Runtime，旧入口直接调用 Router | P0 |
| [`app.routers.focus`](../../app/routers/focus.py) | 阶段与行动 HTTP，发起旧 Agent 交接 | `agent_core`, `focus`, `web`, `workspace` | 调用 Focus/旧任务写入 | FastAPI | 阶段状态、交接、周检查 | 直接取两个 Repository | P1 |
| [`app.routers.income`](../../app/routers/income.py) | 账本、产品验证、机会和复盘 HTTP | `income`, `web` | 调用 Income 写入 | FastAPI | 记账和证据动作 | 业务用例和表单编排集中 | P1 |
| [`app.routers.knowledge_models`](../../app/routers/knowledge_models.py) | 知识、模型预览及用量 HTTP | `content`, `knowledge`, `knowledge_quality`, `knowledge_store`, `model_gateway`, `obsidian`, `resume_studio`, `web`, `workspace` | 调用知识、Vault、模型和索引写入 | FastAPI | 拆卡、地图和模型设置 | 混合知识及模型运维，直接刷新索引 | P1 |
| [`app.routers.resumes`](../../app/routers/resumes.py) | 简历导入、编辑、定制、照片与导出 HTTP | `career`, `model_gateway`, `resume_assets`, `resume_docx`, `resume_import`, `resume_pdf`, `resume_studio`, `web` | 调用 Career、私有文件和模型桥接 | FastAPI、Chromium 经适配器 | 版本、导入、定制和投递快照 | 同时承担字段映射、审批和渲染编排 | P1 |
| [`app.routers.system`](../../app/routers/system.py) | 材料、搜索、回收站、设备、备份与运行设置 HTTP | `backup`, `career`, `content`, `knowledge`, `knowledge_store`, `library`, `obsidian`, `runtime`, `search`, `vault`, `web`, `workspace` | 经各所有者写入和替换主库 | FastAPI、系统服务状态经适配器 | 运维、移动配置、材料操作 | 多域装配和恢复后的依赖重建在路由 | P1 |
| [`app.routers.wechat`](../../app/routers/wechat.py) | 公众号预览确认、凭据与推送 HTTP | `content`, `publishing`, `publishing_theme`, `web`, `wechat` | 调用 WechatPublisher | FastAPI | 外发审批和状态反馈 | 直接编排发布与推送用例 | P2 |
| [`app.routers.workflow`](../../app/routers/workflow.py) | AI 工作项、Hub 操作、控制中心与 SSE HTTP | `database`, `plugins`, `routers.agent_core`, `web`, `workflow_control`, `workflow_store` | 调用 Store/Hub 写入 | FastAPI、Hub 经适配器 | 审批、规则、停止、续跑 | 直接认得 Hub 路径/形状，旧路由回退 | P1 |
| [`app.routers.workspace_content`](../../app/routers/workspace_content.py) | 旧首页、随想、回顾和旧待办 HTTP | `agent_core`, `atomic`, `content`, `focus`, `knowledge`, `knowledge_quality`, `knowledge_store`, `model_gateway`, `obsidian`, `planner`, `web`, `workspace` | 调用 Vault、Focus、旧任务和索引写入 | FastAPI | 内容生命周期与旧看板 | 多域路由承担编排 | P1 |
| [`app.runtime`](../../app/runtime.py) | LaunchAgent 安装、重启、状态和 Tailnet 诊断 | `privacy` | 本机 launchd 配置和服务日志 | launchctl、Tailscale | macOS 运维 | 与插件内部监督职责应分清 | P1 |
| [`app.search`](../../app/search.py) | 来源投影、FTS5、版本比对与查询 | `content`, `database`, `knowledge_store`, `library` | 派生搜索表 | SQLite FTS5 | 索引范围和查询 | Repository 接受整库来源，读取具体业务字段 | P0 |
| [`app.vault`](../../app/vault.py) | Markdown 路径结构迁移及回滚计划 | `content`, `workspace` | Vault 文件布局 | 文件系统 | 旧目录兼容 | 复用 Content/Workspace | P2 |
| [`app.video`](../../app/video.py) | 视频项目、交接包与 OpenCut 检测 | `atomic`, `content` | video-projects 文件 | 文件系统、OpenCut 本机检出 | 分镜、素材与导出格式 | 项目仓储与外部探测同文件 | P2 |
| [`app.web`](../../app/web.py) | 模板装配、共享视图与静态文件边界 | `content`, `privacy`, `video`, `workspace` | 模板环境、路由呈现 | Jinja2/Starlette | 导航与渲染 | 共享层导入 Content、Workspace、Video 和 Privacy | P1 |
| [`app.wechat`](../../app/wechat.py) | 凭据、推送意图、状态与微信草稿 API | `database` | 推送表、意图文件、钥匙串条目 | 微信 HTTPS、macOS Keychain | API、凭据与超时策略 | HTTP 客户端与用例/Repository 同文件 | P2 |
| [`app.workflow`](../../app/workflow.py) | 预览、批准和执行后端装配 | `deepseek_harness`, `llm`, `model_gateway`, `workflow_hub`, `workflow_store` | 通过 WorkflowStore 写入审批 | Harness/Hub 经适配器 | 模型审批和选择 | 构造具体 Provider 和 Hub；持有就绪及 Trace 缓存 | P1 |
| [`app.workflow_control`](../../app/workflow_control.py) | Hub 事实投影、Trace、安全摘要与 SSE | `workflow_hub` | 派生快照和缓存 | Hub 经适配器 | 事件协议和控制中心字段 | 透过 Workflow 持有可变缓存和 Store 引用 | P1 |
| [`app.workflow_hub`](../../app/workflow_hub.py) | Hub 连接、角色凭据、请求与事件流 | — | 内存客户端及凭据 | Autoloop 回环 HTTP | 协议、鉴权和超时 | 协议路径部分仍由调用方决定 | P1 |
| [`app.workflow_store`](../../app/workflow_store.py) | 工作项、批准、候选、回答和验收存储 | `atomic`, `database`, `plugin_paths` | Workflow 表、results、归档视图 | SQLite、文件系统 | 状态事务、关联和文件恢复 | SQL 与文件无共同事务 | P1 |
| [`app.workflow_worker`](../../app/workflow_worker.py) | 派发、领取、执行、回执和中断处理 | `atomic`, `deepseek_harness`, `model_gateway`, `workflow`, `workflow_hub`, `workflow_store` | 调用 WorkflowStore 和 Hub；领取标识 | Autoloop、Gateway/Harness | 协议回执、重试和恢复 | 识别具体 Harness；就绪写入 Workflow 对象 | P1 |
| [`app.workspace`](../../app/workspace.py) | 随想/文章生命周期、修订、回收站及确定性周回顾 | `atomic`, `content` | 私有 Markdown 和调度写入 | 文件系统、PyYAML | Revision、回收与总结 | 文件操作、用例和调度并存 | P1 |
