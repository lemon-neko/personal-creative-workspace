# 羽白工作台

羽白工作台是一套只供作者本人使用的本地个人驾驶舱：接住临时想法，在 Obsidian 中整理知识，推进公众号与视频创作、求职和学习，并通过私人 Tailnet 从 Android 随时记录。

项目采用 FastAPI、Jinja2、HTMX、Markdown 和 SQLite。代码可以保存在私有 GitHub 仓库；想法、知识、简历、职位、模型任务、附件和备份全部保存在仓库之外。

> 当前阶段：本地单用户 Beta。完整成熟度与近期优先级见 [项目状态](PROJECT_STATUS.md)。

## 核心能力

- **工作台与想法**：随手记录、搜索筛选、状态流转、回收恢复和规则周回顾。
- **分层知识库**：以 Obsidian 为主要整理界面，统一维护“知识首页 → 学科地图 → 主题地图 → 知识卡 → 原始来源”。
- **创作发布**：微信公众号正文排版、富文本复制、可选风格润色，以及视频分镜和 Remotion/OpenCut 交接。
- **求职与学习**：候选人档案、项目证据、简历版本、职位跟踪、技能差距、学习任务和项目战役。
- **模型成本治理**：规则、本地模型、人工桥接和默认关闭的外部 API；所有外发先预览再确认。
- **Android PWA**：经 Tailscale Serve 私网记录文字和图片，并在线只读正式知识库。
- **隐私与恢复**：回环监听、CSRF/Host 校验、仓库外数据、安全上传、Git 守卫和 AES-256 备份。

完整功能边界见 [功能清单](docs/FEATURES.md)。

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

安装、手机网关、环境变量、迁移和备份步骤见 [运行与维护](docs/OPERATIONS.md)。

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

详细威胁边界与检查清单见 [安全说明](docs/SECURITY.md)。

## 文档导航

| 文档 | 解决的问题 |
|---|---|
| [文档首页](docs/README.md) | 从哪里开始阅读 |
| [功能清单](docs/FEATURES.md) | 当前到底能做什么、有什么限制 |
| [系统架构](docs/ARCHITECTURE.md) | 模块、数据和关键流程如何连接 |
| [使用手册](docs/USER_GUIDE.md) | 日常如何记录、整理、创作和求职 |
| [运行与维护](docs/OPERATIONS.md) | 如何启动、迁移、备份和排障 |
| [安全说明](docs/SECURITY.md) | 私人数据如何隔离、什么操作禁止 |
| [开发指南](docs/DEVELOPMENT.md) | 如何理解代码、测试并安全扩展 |
| [项目状态](PROJECT_STATUS.md) | 当前成熟度、已知限制和近期优先级 |

## 开发验证

```bash
WORKSPACE_DATA_DIR=/tmp/pcw-test-runtime .venv/bin/pytest -q
.venv/bin/ruff check app tests tools
.venv/bin/python tools/security_guards.py
WORKSPACE_DATA_DIR=/tmp/pcw-import .venv/bin/python -c "from app.asgi import app; print(app.title)"
```

CI 使用锁定依赖和虚构数据，以 Python 3.11 为主版本并保留 Python 3.10 兼容验证；另有高风险模块覆盖率与 Playwright 浏览器验收。测试数量会随功能变化，以实际收集结果为准。

## 明确不做

- 公网部署、多用户账号、云数据库或把私人数据提交到 Git。
- 后台自动调用模型、未经确认生成知识卡或覆盖原始记录。
- 招聘网站自动抓取和投递、邮件同步或 URL 后台抓取。
- 手机端复制 Markdown/SQLite 主库，或开放完整桌面管理能力。
