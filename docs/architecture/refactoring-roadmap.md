# 渐进重构路线图

## 执行顺序

桌面启动与依赖注入、静态注册和进程监督已完成。检索改造随后建立业务投影契约，求职和收入分别落地，工作流最后消除具体后端耦合。任务编号沿用原约定，表中是建议执行顺序。

| 顺序 | 任务 | 依赖与实施切片 | 交付和回退 |
| --- | --- | --- | --- |
| 1 | [Task 02 · Application Bootstrap 与 DI](application-bootstrap.md)（完成） | 抽出桌面容器并保留工厂兼容导出；记录迁移顺序；移动独立装配；私有附件路由验证 Depends。 | 路由、权限、schema、工厂 import 无副作用和 Lifespan 启停对照。拆分提交保留旧工厂桥接以便回退。 |
| 2 | [Task 05 · Plugin Registry 与 Process Supervisor](plugin-runtime.md)（完成） | 先独立源、目录与包校验，使注册只依赖 API；再将 Web 与 Hub 逐项挂到受监督进程。Worker 作为受管协程，launchd 继续负责主服务。 | 降低循环基线；校验健康、退出、停止和启动恢复；保留启动入口、协议、端口与现有私有配置。 |
| 3 | Task 06 · Search Incremental Indexing | 先以现有单条内容更新作对照，接通提交后内容事件与删除；再补知识、求职、视频与外部 Vault 对账。 | 无关写入不扫描，目标更新且并发无陈旧覆盖；保留手工 rebuild。逐来源切换，回退时使用现有同步与重建。 |
| 4 | [Task 03 · Career 领域拆分](career-domain.md)（完成） | 已建立四个领域、兼容入口和共享事务。Career 搜索投影随 Task 06 推进。 | 保留同一 SQLite 事务、快照、迁移和 API；逐个切片回退到兼容 Repository。 |
| 5 | [Task 04 · Agent Runtime 领域拆分](agent-runtime.md)（完成） | 已拆分领域、服务、执行器和存储，保留旧路由及数据。 | 旧运行状态和人工确认回归；Autoloop 保持独立。 |
| 后续 | Income 领域拆分 | 在 Task 02 后可独立推进。先抽金额/证据规则，再分账本、首品、机会证据/复盘。 | 账本与验证一致，历史迁移测试仍过；逐个切片回退。 |
| 6 | Task 07 · Workflow 与 Integration 边界 | Task 02/05 后先把协议路径、就绪和执行器从 Workflow 取出，明确审批、派发、执行和投影端口；再完善恢复演练。 | 真实 Hub、虚构模型联调；未知结果不会重放，副作用可对账。保持上游协议、事件 ID 和恢复语义。 |

系统 API 的材料、搜索、运行、备份和设备入口随其所有者逐步归位。恢复停写与多源对账先给出独立变更和隔离演练，避免夹在业务拆分中上线。每个切片先锁住契约，再移动代码，最后移除已失效的过渡引用。风险和验收详见[审计报告](audit-report.md)。

## 搜索落地路径

1. 用现有 fixture 记录来源读取次数、渲染范围与写入耗时。保留同一 SQLite FTS5。
2. 让作者数据提交后通知 `kind + id + revision + operation`。事件携带引用与版本，内容由所有者按白名单投影。若事务内没有可靠通知，使用启动和手动对账弥补；有实际丢失证据时再评估持久事件。
3. 复用单条 upsert，增加删除键；以来源最新状态校验、串行化相同键或用版本条件更新，防止旧事件或全量对账覆盖较新结果。
4. 全量流程只保留启动修复、显式重建与 Obsidian 外部改动对账。验证移动、删除、重试、归档、中文召回和敏感字段排除。

## 外部进程监督落地路径

每个服务声明启动命令、只读健康探针、启动/停止期限和日志策略。Supervisor 区分 `starting / ready / degraded / stopped / failed`，在异常后按有上限的退避恢复，超过预算显示失败和最近安全退出原因。人工停止先标记期望状态，再取消重启和终止进程。进程组回收、过期探针、stdout/stderr 有界脱敏及 Worker 协程退出都纳入测试。保留工作台独占锁、Web CSP 探测和 Hub 角色认证；两套服务分别报告健康。

## 架构检查状态

| 状态 | 规则 | 实现和边界 |
| --- | --- | --- |
| Enforced | 新循环边禁止，旧边解决后同步收紧 | AST 完整扫描本地显式 import，精确固定旧循环内的边；覆盖相对和延迟导入。动态分派与 SQL 由审计补充。 |
| Enforced | 业务不能反向 import 组合入口；现有适配器不能直接导入 Router | 检查明确的 ASGI/工厂边与现有五个外部适配器。 |
| Enforced | 桌面 Router 无底层 SQL 调用；工厂导入无数据根创建 | 检查 Router 的 SQLite 连接及执行调用，另以独立进程验证工厂导入。运行工厂和 ASGI 的验证使用临时目录。 |
| Enforced | 数据表、所有者和注册版本可核对 | 从文档读取归属与版本，比较隔离初始化的真实 schema，检测漏报或重复归属。现有迁移测试验证事务和回滚。 |
| Planned | Domain 禁 FastAPI/数据库，Application 禁 Router，Integration 只实现端口 | Agent Runtime 已检查 Domain、Application 和 Executor 的内部导入方向；其他混合模块逐个迁移。 |
| Planned | 全域 SQL 写入边界和故障隔离 | SQLite 归属校验不分析 SQL 读写语义。旧 Agent 已通过适配器保留关联和派生活动的同一事务；Task 05 已验证外部进程和 Worker 故障隔离。 |
| Planned | Provider 全经适配器、按用例注入可替换依赖 | 现有 Workflow 和 Gateway 有具体 Provider 依赖；Task 02/07 收敛后再启用全量规则。 |

架构检查随现有 Pytest 流程运行。开发者可以单独执行 `.venv/bin/python -m pytest -q tests/architecture`。
