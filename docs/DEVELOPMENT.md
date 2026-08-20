# 开发指南

本文面向后续维护工程师和 AI Agent。任何修改都必须先遵守根目录 [AGENTS.md](../AGENTS.md) 和 [安全说明](SECURITY.md)。

## 技术栈

- Python、FastAPI、Uvicorn
- Jinja2 服务端模板与 HTMX 渐进增强
- markdown-it-py 与本地 MathJax
- PyYAML 和 Markdown front matter
- 标准库 SQLite、FTS5 和事务
- 本地 D3 知识图
- Android PWA、Service Worker 和 IndexedDB
- Tailscale Serve 私网代理
- Pytest、Ruff 和 GitHub Actions

项目没有前端构建系统、ORM、云数据库、外部向量库或公开 JSON API。

## 代码结构

| 模块 | 责任 |
|---|---|
| `app/main.py`、`app/asgi.py` | 纯桌面应用工厂与生产 ASGI 入口 |
| `app/routers/`、`app/web.py` | 五组桌面 Router、共享模板、静态资源和错误响应 |
| `app/content.py` | `ContentItem`、Markdown 解析、诊断、安全渲染和 Revision |
| `app/workspace.py` | 内容创建、编辑、状态、回收、规则周回顾和工作台设置 |
| `app/knowledge_store.py` | 正式知识地图、知识卡、关系校验、替代历史和核心图 |
| `app/obsidian.py` | Vault 扫描、Templates、分层链接、外部编辑协调和旧结构迁移 |
| `app/library.py`、`app/search.py` | 材料记录、FTS5 增量索引和统一检索 |
| `app/publishing.py`、`app/video.py` | 微信渲染、文章派生、视频项目和制作交接 |
| `app/career.py` | 求职、学习、项目战役、私有文档和 SQLite 关系 |
| `app/model_gateway.py`、`app/llm.py` | Provider 策略、任务、Token/费用和 OpenAI-compatible 客户端 |
| `app/mobile.py`、`app/mobile_main.py`、`app/mobile_asgi.py` | 移动存储、纯工厂、生产入口、捕获事务、配对和 PWA 路由 |
| `app/mobile_knowledge.py` | 移动端只读地图、知识卡、来源和 Markdown 安全投影 |
| `app/privacy.py`、`app/atomic.py` | 数据根、权限、CSRF、本地访问和原子文件写入 |
| `app/database.py` | SQLite 统一连接、版本登记、升级快照和事务迁移 |
| `app/runtime.py`、`app/recovery.py` | launchd 运行管理、状态检查、恢复锚点和隔离演练 |
| `app/backup.py`、`app/vault.py` | AES-256 备份与生命周期目录迁移 |

模板位于 `app/templates/` 和 `app/mobile_templates/`；共享宏位于 `app/templates/macros/`。桌面与移动 CSS 均按基础变量、通用组件和领域页面拆分。静态目录不得包含私人内容。

## 应用装配

- `create_app()` 创建桌面应用，注入内容目录、SQLite Repository、模型网关、Obsidian Bridge、视频 Repository 和安全中间件。
- `create_mobile_app()` 创建最小移动应用，只装配移动会话、捕获服务和只读知识投影。
- 导入上述工厂不得创建数据库、修改目录权限或读取真实 Vault；`app.asgi` 与 `app.mobile_asgi` 才创建生产应用。
- `python -m app` 固定启动桌面 `127.0.0.1:8765`。
- `python -m app.mobile_launcher` 先验证 Tailscale 状态，再启动 `127.0.0.1:8766`。
- 测试应显式传入临时目录和关闭调度器，不能读取作者默认数据根。

## 存储选择

### Markdown

适用于需要长期阅读、Obsidian 编辑、Git 外迁移和人工审阅的内容：

- 想法、文章和周回顾
- 学科地图、主题地图和知识卡
- 阅读材料记录

解析错误产生诊断，不应阻断其他文件加载。未知 Obsidian Properties 必须保留。

### SQLite

适用于结构化关系、状态查询、幂等记录和可重建索引：

- 求职、学习和项目战役
- FTS5 搜索索引
- 模型价格和用量元数据
- Obsidian 文件 Revision 状态
- 移动设备、会话和幂等回执

移动数据库与主数据库分离，不进入内容同步。任何 schema 变化都必须加入对应迁移序列。主库使用 `schema_migrations`，移动库使用 `mobile_schema_migrations`；禁止新增模块自行维护另一套版本表。

### 私有文件

上传文档、图片、视频交接包和加密备份保存在数据根下的独立目录。使用随机存储名、私有权限和受保护下载路由。

## 路由分组

桌面页面按以下稳定入口组织：

- 工作台与内容：`/`、`/ideas`、`/reviews`、`/trash`
- 知识与材料：`/knowledge`、`/library`、`/search`
- 创作：`/publish`、`/video`
- 求职与学习：`/career`、`/learning`
- 模型：`/models`、`/model-tasks/{id}`
- 系统：`/settings`、`/settings/obsidian`、`/settings/mobile`、`/settings/backups`
- 运行与索引：`/settings/runtime`、`/settings/search`

移动页面只包含 `/`、`/knowledge`、地图/卡片详情、配对、会话、最近记录和捕获接口。新增移动能力必须证明不能通过它访问桌面管理数据。

项目不提供外部公共 API。JSON、SSE 或内部移动接口都属于本机或 Tailnet 内部实现，不能视为稳定的第三方集成契约。

## 内容与知识约束

- 新想法只要求正文；标题和摘要可派生。
- `ContentItem` 类型与状态使用固定枚举，未知值生成诊断。
- 正文更新后，旧知识整理状态必须失效。
- 正式知识只由 `KnowledgeMap` 和 `KnowledgeCard` 驱动。
- 知识卡必须至少有一个 `source_id`，关系目标必须存在。
- 多父级地图允许跨学科，但禁止循环。
- 新观点不覆盖旧卡；冲突和替代保留历史。
- 生成的 Obsidian 链接区块从正文、搜索、模型和发布输入中排除。

## 模型功能约束

新增模型任务时必须：

1. 定义固定任务类型和 `ModelPolicy` 上限。
2. 在服务端生成明确的外发预览。
3. 允许选择 rules/local/manual/external 中适用的 Provider。
4. 拒绝非回环 local 地址和默认关闭的 external。
5. 校验结构化输出、来源 ID、数量和关系目标。
6. 把结果保存为候选，等待第二次确认写入。
7. 账本只写用量元数据，不写正文、提示词、响应或密钥。

定时任务不得调用模型。

## 文件修改约束

- 使用 `content_lock()` 保护跨进程 Markdown 写入。
- 使用原子写入工具，不直接覆盖权威文件。
- 先验证目标位于允许目录内，再执行移动、读取或删除。
- 不依赖未解析的环境变量、通配符或用户文件名定位删除目标。
- 删除保持可恢复；永久删除需要严格确认词。
- 编辑表单必须携带 Revision，冲突返回 409。

## 测试组织

| 测试文件 | 覆盖领域 |
|---|---|
| `test_content.py`、`test_workspace.py` | Markdown、生命周期、周回顾和设置 |
| `test_knowledge.py`、`test_knowledge_store.py` | 旧兼容层、正式地图/卡片、关系和核心图 |
| `test_obsidian.py` | Properties、Revision、模板、分层链接、迁移与回滚 |
| `test_publishing.py`、`test_video.py` | 微信正文、安全渲染、分镜和交接文件 |
| `test_career.py` | 求职、文档、职位、技能和战役 |
| `test_model_gateway.py`、`test_llm.py` | Provider、上限、人工导入、用量和客户端 |
| `test_mobile.py` | 配对、会话、捕获、离线边界和移动知识投影 |
| `test_library_search.py` | 材料和本地统一搜索 |
| `test_backup.py` | 加密、篡改、版本和恢复回滚 |
| `test_database.py`、`test_recovery.py` | 统一迁移、事务回滚、恢复锚点和隔离演练 |
| `test_app.py` | 页面、路由、安全中间件和跨模块烟雾测试 |
| `tests/browser/` | Playwright 桌面创作和移动离线/知识关键流程 |

## 验证命令

```bash
WORKSPACE_DATA_DIR=/tmp/pcw-test-runtime .venv/bin/pytest -q
.venv/bin/ruff check app tests tools
.venv/bin/python tools/security_guards.py
.venv/bin/python tools/check_coverage_targets.py
WORKSPACE_DATA_DIR=/tmp/pcw-import .venv/bin/python -c "from app.asgi import app; print(app.title)"
```

定位问题时可以先运行相关测试文件，但交付前仍需运行完整验证。CI 以 Python 3.13 为主，保留 Python 3.11 兼容，独立执行 Ruff、高风险覆盖率和 Playwright。

## 扩展检查表

### 新页面或表单

- [ ] 放入正确导航分组，支持窄屏和无 JavaScript 基础流程。
- [ ] 私人响应 `no-store`，POST 有 CSRF 和同源检查。
- [ ] 不返回私人绝对路径、正文日志或未授权附件。
- [ ] 有 TestClient 成功、失败、404 和越权测试。

### 新数据类型

- [ ] 明确 Markdown、SQLite 或私有文件中的唯一权威来源。
- [ ] 定义校验、重复 ID、迁移、备份和恢复行为。
- [ ] 文件写入原子化，SQLite 更新使用事务。
- [ ] 私有数据路径被 `.gitignore` 和安全守卫覆盖。

### 新模型能力

- [ ] 无后台调用，外发材料可预览和脱敏。
- [ ] 有输入/输出上限、超时、非法响应和人工确认。
- [ ] 候选与已确认数据分离，来源不被覆盖。
- [ ] 用量账本不保存敏感正文。

## 文档维护

- 新功能或行为变化首先更新 [功能清单](FEATURES.md)。
- 架构或数据流变化更新 [系统架构](ARCHITECTURE.md)。
- 用户步骤变化更新 [使用手册](USER_GUIDE.md) 或 [运行与维护](OPERATIONS.md)。
- 安全边界变化同时更新 [安全说明](SECURITY.md) 与 `AGENTS.md`。
- 成熟度和优先级变化只更新根目录 `PROJECT_STATUS.md`。
- README 只保留入口摘要，不复制详细流程。
