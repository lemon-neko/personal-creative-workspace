# 目标架构

桌面 Bootstrap 已在 [Task 02](application-bootstrap.md) 实施。下文同时记录后续目标与迁移边界。

保留单用户 Local-first、FastAPI + Jinja/HTMX、SQLite + Markdown，以及 Super Productivity 和 Autoloop 的独立运行边界。目标是 Modular Monolith，在各领域以用例切片组织代码，在持久化和外部调用处按需引入 Ports & Adapters。目录随验证通过的切片建立。

```text
app/
├── __main__.py / asgi.py / main.py        # 入口与兼容导出
├── bootstrap/                            # 工厂、装配容器、生命周期、迁移编排
├── core/                                 # 配置、访问边界及被多个模块复用的契约
├── modules/                              # 日常、AI、知识、创作、求职、收入、阶段、助手
├── integrations/                         # SP、Autoloop、模型、Harness、Obsidian、移动
├── platform/                             # SQLite、文件、搜索、备份、注册表、进程监督
└── web/                                  # 共享模板环境、静态资源与 Web 适配
```

## 依赖与装配

- `bootstrap` 创建具名的 AppContainer，使用显式构造参数连接 Repository、Adapter 和 Application Service。FastAPI `Depends` 在 API 层取用例所需的少量依赖。过渡期保留 `app.state` 兼容引用，单个切片迁移成功后再缩小。
- Domain 维护实体与规则；Application 编排审批、状态和事务，定义其真正需要的读写接口；API 负责输入、错误和响应投影；Infrastructure 实现表和文件；Integration 实现外部协议。只有复杂切片才需要全部层。接口服务调用方，避免为每个函数建立接口。
- 外层依赖内层。Application 使用自己定义的端口，持久化及集成适配器实现端口，领域间通过用例或只读投影通信。旧 Agent 与阶段行动需要保持同事务，由一个明示事务边界调用两边的仓储能力。SQLite 与 Vault、Hub 等跨存储操作使用稳定标识及恢复核对。
- `create_app` 现有签名及 `app.asgi:app` 保持可用。装配顺序显式呈现数据根、迁移和服务构建；Lifespan 负责可撤销资源与后台任务，退出逆序释放。静态装配只引用内置功能，不从数据目录加载 Python。
- Route name、HTTP method/path、响应与模板引用、CSRF、Origin 和回环边界都视为契约。新的适配器保留失败状态和恢复语义。数据库版本和业务目录移动另行评审。

## 代码迁移映射

| 当前入口 | 目标切片与落点 | 优先级 | 风险与验收重点 |
| --- | --- | --- | --- |
| `main.py`、`asgi.py`、`mobile_main.py`、`mobile_asgi.py` | `bootstrap/app_factory`、`container`、`lifespan`；移动入口保留独立安全组合 | P0 | 高。兼容测试注入、导入无副作用、停机顺序和两个应用的权限。 |
| `database.py` 和各 Repository 的迁移调用 | `platform/database` 执行器；`bootstrap/migrations` 显式编排，迁移 SQL 归领域 | P0 | 高。Focus 先于旧 Agent；可选 Workflow、旧库检测、快照和失败回滚均需覆盖。 |
| `plugins.py`、`install_plugins.py`、`plugin_runtime.py`、`plugin_web.py`、`runtime.py` | `platform/plugins` 静态注册与包验证；`platform/process` 监督；SP/Autoloop adapters 自管协议与健康探针；launchd 保留宿主职责 | P0 | 高。固定版本、两个进程的故障隔离、独立源、锁和权限须保持。 |
| `search.py`、`main.py` 中间件、`routers/system.py` 检索 | `platform/search` 的查询、投影索引和对账；业务模块注册安全字段投影 | P0 | 中高。保留 FTS5、中文查询、结果 URL、索引隐私及离线对账。 |
| `career.py`、`routers/career_learning.py` | `modules/career` 的档案/证据、投递、学习切片；同一 Career 迁移体系 | P1 | 高。投递字段更新和阶段事件原子，旧路由、快照与状态迁移保持。 |
| `routers/resumes.py`、`resume_*.py` | Career 简历切片，分离编辑与匹配、导入确认、定制与导出；DOCX/PDF 为适配器 | P1 | 高。主简历保护、Revision、照片引用、JD 与人工确认保持。 |
| `income.py`、`routers/income.py` | `modules/income` 的现金账本、首品验证、机会证据/复盘切片 | P1 | 高。金额整数、现金归集、归档锁定及跨切片条件同事务。 |
| `routers/system.py` | 材料归知识，回收站归内容生命周期，设备归移动；搜索、备份、运行各归平台 API | P1 | 中高。路由名、模板、恢复预演、确认词和本机权限均保留。 |
| `workflow*.py`、`routers/workflow.py` | `modules/ai_workflow` 审批、执行/恢复、控制投影；`integrations/autoloop` 实现事件和领取端口 | P1 | 高。审批指纹、稳定事件 ID、幂等领取和未知结果重审。 |
| `model_gateway.py`、`llm.py`、`deepseek_harness.py` | `integrations/model_gateway` 网关、账本、人工任务和 providers；输出校验由相应切片注册 | P1 | 中高。Worker 不做具体 Provider 类型判断；用量、隐私、调用门槛保持。 |
| `content.py`、`workspace.py`、`knowledge*.py`、`library.py`、`obsidian.py` | 内容生命周期及知识切片，链接解析置于上层，Obsidian 作为同一 Vault 的适配器 | P1 | 中高。原始 YAML、Revision、相对链接、外部编辑冲突。 |
| `focus.py`、`planner.py`、`agent_core.py`、`assistant.py` | 阶段、旧待办、旧 Agent、助手独立用例及稳定引用 | P1 | 中高。旧入口、隐藏目标、助手确认和幂等保留。 |
| `publishing*.py`、`video.py`、`wechat.py`、`web.py` | 创作切片、微信/OpenCut 适配与共享 Web 装配 | P2 | 中。只接受文章，二次确认、脱敏回执及导出结构保持。 |

## 参考项目与本项目取舍

- Super Productivity 的操作日志、同步和插件数据披露分别记录在上游文档中。工作台据此保留浏览器任务权威，用只读投影及显式交接衔接；后续重要边界以简短 ADR 记录。 [操作日志架构](https://github.com/super-productivity/super-productivity/blob/v20.0.0/docs/sync-and-op-log/operation-log-architecture.md) [插件开发文档](https://github.com/super-productivity/super-productivity/blob/v20.0.0/docs/plugin-development.md)
- n8n 将 workflow、core、节点集成放在不同包。工作台借鉴执行、协议与集成职责分离，部署仍为本机单体和现有上游进程。 [n8n packages](https://github.com/n8n-io/n8n/tree/master/packages)
- OpenHands SDK 分开 Agent SDK、工具、Workspace 和 Agent Server。工作台据此把审批、执行器、文件权限与 Provider 的依赖拆开。 [OpenHands SDK 结构](https://github.com/OpenHands/software-agent-sdk) [架构说明](https://docs.openhands.dev/sdk/arch/overview)
- Autoloop 把事件提交、接单和卡片回答作为 Hub 边界。工作台保留协议和 Hub 权威，将签发审批和执行适配留在本地。 [Autoloop v1.8.1 协议](https://raw.githubusercontent.com/KKKKhazix/agent-autoloop/v1.8.1/docs/protocol.md)
- FastAPI 提供 Router 组合、依赖注入和 Lifespan。工作台采用原生能力支撑装配与测试替换。 [Router 组合](https://fastapi.tiangolo.com/tutorial/bigger-applications/) [Lifespan](https://fastapi.tiangolo.com/advanced/events/)
