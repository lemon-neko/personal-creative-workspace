# 羽白工作台

羽白工作台是一套本地单用户工作台。用「日常工作」安排待办和计时，用「AI 工作流」确认模型请求并验收产物。工作台也提供主线与分支、创作、求职和学习入口，并支持在 Obsidian 整理知识、从 Android 私网记录随想。

项目采用 FastAPI、Jinja2、HTMX、Markdown 和 SQLite。想法、知识、简历、职位、模型任务、附件和备份全部保存在源码仓库之外。

> 当前阶段：本地单用户 Beta。完整成熟度与近期优先级见 [项目状态](PROJECT_STATUS.md)。

## 核心能力

- **日常工作与主线**：桌面插件启用后，首页提供 Super Productivity 的待办、月历与计时。主线与分支另有入口。
- **AI 工作**：待办可交接给 Agent；预览后执行，必要时等你拍板，候选产物由本人验收。
- **想法与回顾**：想法库管理随想，文章与周回顾分别管理。旧待办保留随想快速记录入口。
- **分层知识库**：以 Obsidian 为主要整理界面，统一维护“知识首页 → 学科地图 → 主题地图 → 知识卡 → 原始来源”；单条随想可安全拆卡并用来源 Revision 追踪变化。
- **创作发布**：独立文章草稿才可进入微信公众号排版和视频制作；普通随想、周回顾与知识卡不会误入发布台。
- **求职与学习**：候选人档案、项目证据和简历版本保持独立；投递表从空白开始，内置 Agent 工程路线按四个阶段用动手实践、测试和复盘推进。
- **个人决策助手**：基于经过压缩的工作台状态回答“现在先做什么”；每轮先预览外发内容，引用可回到站内来源，候选行动必须逐项确认。
- **模型成本治理**：规则、本地模型、人工桥接和默认关闭的外部 API；所有外发先预览再确认。
- **Android PWA**：通过 Tailscale Serve 私网查看日常看板，离线新建和编辑随想，联网同步并处理 Revision 冲突。
- **隐私与恢复**：回环监听、CSRF/Host 校验、仓库外数据、安全上传、Git 守卫和 AES-256 备份。

完整功能边界见 [功能模块](docs/features/README.md)。

## 五分钟启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python -m app
```

浏览器访问 <http://127.0.0.1:8765>。不要使用 `--host 0.0.0.0`。

默认私有数据目录：

```text
~/Library/Application Support/personal-creative-workspace/
```

需要临时使用其他目录时：

```bash
WORKSPACE_DATA_DIR=/absolute/private/path .venv/bin/python -m app
```

安装、手机网关、环境变量、迁移和备份步骤见 [运行维护](docs/operations/README.md)。首次体验可使用仓库外的临时目录。完整日常工作与 AI 界面需要另外安装 [桌面插件](docs/operations/workbench-plugins.md)。

需要让工作台随登录常驻运行时，使用显式本机管理命令：

```bash
.venv/bin/python -m app.runtime install
.venv/bin/python -m app.runtime status
```

## 安全边界

- 桌面服务只监听 `127.0.0.1:8765`，不提供公网部署、账号或多用户能力。
- 移动网关只监听 `127.0.0.1:8766`，仅允许 Tailscale Serve 私网代理，禁止 Funnel。
- 私有内容不进入 Git、`/static`、日志或公开 CI artifact。
- Obsidian 直接打开私有 `content/` 目录，不启用 Obsidian Sync、Local REST API 或来源不明的社区插件。
- 外部模型默认关闭；任何模型任务都必须先展示即将发送的材料。
- 磁盘静态数据依赖 macOS FileVault，请保持 FileVault 开启。

详细威胁边界与检查清单见 [隐私与恢复](docs/features/privacy-recovery.md)。

## 文档导航

| 文档 | 解决的问题 |
|---|---|
| [文档首页](docs/README.md) | 从哪里开始阅读 |
| [功能模块](docs/features/README.md) | 每个功能当前能做什么、有什么限制 |
| [系统架构](docs/architecture/README.md) | 技术栈、运行拓扑、数据流和权威存储 |
| [操作指南](docs/guides/README.md) | 日常如何记录、沉淀、创作和求职 |
| [运行维护](docs/operations/README.md) | 如何启动、迁移、备份和排障 |
| [开发说明](docs/development/README.md) | 如何理解代码、测试并安全扩展 |
| [更新档案](docs/changes/README.md) | 每个已完成功能批次改了什么 |
| [项目状态](PROJECT_STATUS.md) | 当前成熟度、已知限制和近期优先级 |

## 开发验证

```bash
WORKSPACE_DATA_DIR=/tmp/pcw-test-runtime .venv/bin/pytest -q
.venv/bin/ruff check app tests tools
.venv/bin/python tools/security_guards.py
WORKSPACE_DATA_DIR=/tmp/pcw-import .venv/bin/python -c "from app.asgi import app; print(app.title)"
```

CI 使用锁定依赖和虚构数据，以 Python 3.13 为主版本并保留 Python 3.11 兼容验证；另有高风险模块覆盖率与 Playwright 浏览器验收。测试数量会随功能变化，以实际收集结果为准。

## 明确不做

- 公网部署、多用户账号、云数据库或把私人数据提交到 Git。
- 后台自动调用模型、未经确认生成知识卡或覆盖原始记录。
- 招聘网站自动抓取和投递、邮件同步或 URL 后台抓取。
- 手机端复制 Markdown/SQLite 主库，或开放完整桌面管理能力。

## 许可证

工作台原创代码与文档采用 [MIT 许可证](LICENSE)。随源码分发的前端库沿用各自的[上游许可证](app/static/vendor/README.md)。
