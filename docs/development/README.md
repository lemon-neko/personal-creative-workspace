# 开发说明

修改仓库前必须先阅读根目录 [AGENTS](../../AGENTS.md)、[系统架构](../architecture/README.md) 和 [隐私与恢复](../features/privacy-recovery.md)。

## 技术栈

- Python、FastAPI、Uvicorn
- Jinja2 服务端模板与 HTMX 渐进增强
- markdown-it-py、本地 MathJax 和 PyYAML
- 标准库 SQLite、FTS5 和事务
- 本地 D3 知识图
- Android PWA、Service Worker 和 IndexedDB
- Tailscale Serve
- Pytest、Ruff、Playwright 和 GitHub Actions

项目没有前端构建系统、ORM、云数据库、外部向量库或公共 API。

## 前端视觉契约

- `app/static/styles/design-system.css` 是全站视觉令牌与最终覆盖层；历史页面样式继续保留业务布局职责。
- 视觉方向固定为克制的编辑部控制台：冷灰中性色、单一羽白青、纸张式表面和清晰的信息密度。
- 卡片与输入控件分别使用统一圆角，不通过厚重阴影、渐变、装饰图形或重复英文眉题制造层级。
- 页面必须保持键盘焦点、可读对比度、窄屏横向导航和 `prefers-reduced-motion` 降级。
- 新页面优先复用现有按钮、表单、面板、状态和页面标题样式；不引入前端构建系统或新的 UI 框架。

## 代码模块

| 模块 | 责任 |
|---|---|
| `app/main.py`、`app/asgi.py` | 纯桌面应用工厂与生产入口 |
| `app/routers/`、`app/web.py` | 桌面 Router、模板、静态资源和错误响应 |
| `app/content.py`、`app/workspace.py` | 内容解析、Revision、生命周期、回顾和工作台服务 |
| `app/knowledge_store.py`、`app/obsidian.py` | 正式知识、关系、来源、Vault 扫描和迁移 |
| `app/library.py`、`app/search.py` | 材料和增量 FTS5 检索 |
| `app/publishing*.py` | 微信预处理、语义渲染、主题和导出编排 |
| `app/career.py`、`app/career_radar.py` | 求职、学习、岗位雷达和项目证据 |
| `app/assistant.py` | 助手上下文、校验、摘要与确认行动 |
| `app/model_gateway.py`、`app/llm.py` | Provider、策略、用量和客户端 |
| `app/mobile*.py` | 移动工厂、会话、离线同步、冲突和知识投影 |
| `app/privacy.py`、`app/atomic.py` | 数据根、权限、安全校验和原子写入 |
| `app/database.py` | SQLite 连接、迁移、事务和快照 |
| `app/runtime.py`、`app/recovery.py` | launchd、运行状态和恢复演练 |
| `app/backup.py`、`app/vault.py` | 加密备份与生命周期迁移 |

## 应用装配约束

- `create_app()` 和 `create_mobile_app()` 只装配依赖、路由和中间件。
- 导入应用工厂不得创建数据库、修改默认目录权限或读取真实 Vault。
- 生产 ASGI 入口负责创建真实应用；测试必须显式注入临时目录并关闭调度器。
- `python -m app` 固定启动 `127.0.0.1:8765`；移动启动器固定使用 `127.0.0.1:8766`。

## 路由和数据约束

- 桌面按内容、知识模型、创作、求职学习和系统设置分组。
- 移动只暴露记录、随想编辑、精简拆卡和知识阅读，不能访问桌面管理数据。
- 新知识卡必须来自未归档随想、归入主题并记录来源 Revision。
- 公众号和视频只接受文章；历史关系只保持读取兼容。
- SQLite schema 变化必须进入主库或移动库统一迁移序列。
- 文件写入必须使用锁、原子替换和路径边界校验。

## 模型能力约束

新增模型任务必须定义 `ModelPolicy`，生成可编辑外发预览，限制 Provider 和 Token，校验结构化结果及引用 ID，并把结果保存为候选等待确认。账本不得写入正文、提示词、响应或密钥。定时任务不得调用模型。

助手额外要求来源和技能白名单、最小持久化，以及只允许逐项确认创建随想或学习任务。

## 扩展检查表

- 新页面：导航、窄屏、无 JavaScript、CSRF、`no-store`、404 和越权测试。
- 新数据：唯一权威来源、校验、迁移、备份、恢复和 Git 排除。
- 新模型：外发预览、上限、超时、非法响应、候选隔离和确认写入。
- 新上传：签名、大小、文件名、随机存储名、路径和失败回滚。
- 新移动能力：证明不会扩大到桌面管理数据，并验证离线与撤销边界。

测试和 CI 见 [测试说明](testing.md)。

## 文档维护

一个功能批次完成时：

1. 更新对应 `docs/features/` 模块文档。
2. 按 [更新模板](../changes/TEMPLATE.md) 新增 `docs/changes/YYYY/` 记录，并更新变更索引。
3. 数据流或系统边界变化时更新 `docs/architecture/`。
4. 用户步骤变化时更新 `docs/guides/` 或 `docs/operations/`。
5. 成熟度变化时更新根目录 `PROJECT_STATUS.md`。
6. 安全边界变化时同时更新功能文档和根目录 `AGENTS.md`。

README 只保留项目入口和摘要，不复制模块细节。更新记录只描述已实现并验证的事实，不保存计划或私人内容。
