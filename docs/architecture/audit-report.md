# Task 01 · 架构基线审计报告

## 审计范围与证据

- 工作区起点为本地 `main`，提交 `6a8375e`，Git 显示与本地追踪引用 `origin/main` 同步，工作区干净。基线以本地代码及隔离运行结果为准。
- 扫描 `app/` 全部 70 个 Python 模块。另检查桌面和移动入口、HTTP 和 Worker 调用、SQL 及表约束、外部协议、恢复脚本、README、AGENTS、PROJECT_STATUS 和现有架构文档。逐模块结果见[模块清单](module-map.md)，真实依赖见[依赖图](dependency-map.md)。
- 依赖由 `requirements.txt`、`requirements-dev.txt`、`requirements.lock` 和 `.python-version` 管理；无 `pyproject.toml`。Ruff 使用独立 `ruff.toml`，目标语法为 py310。CI 使用 Python 3.11/3.13、锁定依赖、关键模块覆盖率门槛及 Playwright Chromium 浏览器任务；固定上游包和 Harness 联调需按环境变量另启用。 [CI](../../.github/workflows/ci.yml)
- 核验 SQLite 只使用临时数据目录；记录 245 个桌面、17 个移动的路由/挂载项，以及带可选 Workflow 的完整两库 schema 和迁移版本。审计依据为源码、可复现测试和固定版本上游资料。未访问真实 Vault、生产数据库、线上模型或手机。

## A. 架构评分

分值代表可独立核验的成熟度。1 为缺少明确边界，2 为有接口但常需读取其他实现，3 为主路径清楚且可测并存在已定位缺口，4 为边界和失败路径已有稳定验证，5 还要求约束可持续执行并覆盖主要异常与恢复组合。分数按审计基线评估。

| 维度 | 分数 | 依据 |
| --- | ---: | --- |
| 模块化程度 | 3/5 | 13 个桌面路由模块、独立移动入口，Workflow 已分离 Store、Hub、Worker 和投影；Career 和系统路由仍跨多个用例和所有者。 |
| 依赖关系 | 2/5 | AST 得 238 条内部导入，52 条落在两个循环分量；另有 `app.state` 注入、同库跨域 SQL 和模型验证回引。 |
| 数据所有权 | 3/5 | Vault、主库、移动库、Hub、浏览器和私有结果各有权威；旧 Agent 同事务写入 Focus 活动，标准恢复未涵盖完整 AI 及设备状态。 |
| 插件扩展性 | 2/5 | 10 个可信内置 Feature 有路由、导航及声明字段，两个上游包各自校验；声明字段未形成通用权限/依赖执行器，目录/源常量与注册耦合。 |
| Agent 执行架构 | 4/5 | 每轮审批、稳定派发标识、持久化领取、超时重审和恢复有真实 Autoloop 测试；Worker 识别 Harness，主库、Hub 和文件仍需人工配套恢复。 |
| 可测试性 | 4/5 | 工厂可注入目录与模型，HTTPX 可注入 transport；临时 SQLite、Playwright、真实 Hub/Harness 路径可运行。部分依赖由 state 或模块补丁替换。 |
| 可维护性 | 3/5 | 有统一迁移和细分文档；Career、Income 和系统 API 同时维护不同业务不变量，改变恢复/搜索的影响跨多个模块。 |
| 故障隔离 | 3/5 | 损坏 Web 包、Hub 包和无效 Harness 有双向回退测试；共享锁与启动异常会越过隔离，子进程固定重启且后台任务异常缺少独立诊断。 |

## B. 问题优先级

P0 是后续重构的前置问题或可能放大故障范围的架构风险；P1 是需要保留业务不变量的切片改造；P2 是现有能力稳定且可逐步清理的依赖。P0 用于安排重构顺序，未宣称生产出现对应故障。

| 优先级 | 问题 | 证据 |
| --- | --- | --- |
| P0 | 启动装配与迁移隐式耦合 | 工厂同步初始化两库、Repository、seed、插件配置；Lifespan 又恢复、扫描检索和启动任务。Focus 与旧 Agent 外键限制构造顺序。 [工厂](../../app/main.py) [迁移](../../app/database.py) |
| P0 | 搜索同步扫描范围过大 | 成功的桌面写方法完成后，除显式重建和 `/workflow/` 外会同步所有来源，包括非搜索相关写入；部分路由已经提前单条刷新。FTS 写入按 Revision 差异，瓶颈候选是源枚举、解析和重复投影。以临时目录成功提交 `POST /models/pricing` 复现再次收集全部五组来源。未测生产延迟。 [中间件](../../app/main.py) [索引](../../app/search.py) |
| P0 | 外部进程缺少可诊断的监督状态 | `supervise` 丢弃 stdout/stderr，退出及启动 OSError 每 2 秒无限重试，无退避、重启预算或退出码记录。取消时终止、4 秒后强杀，与异常退出走不同控制流，却没有显式可查询状态。Web HEAD 和 Worker ready 独立于监督器。 [运行监督](../../app/plugin_runtime.py) |
| P0 | Feature 注册与外部运行职责混用 | `Plugin` 收集静态元数据及 APIRouter；权限由路由、安全层与 Provider 落实，清单字段并未驱动校验。源和路径常量反向被 Privacy、Store、安装器引用，参与循环。 [注册表](../../app/plugins.py) |
| P0 评估 / P1 迁移 | 大型模块的业务边界未显式化 | Career 2,274 行、Income 1,691 行、System 路由 897 行、Career/Learning 路由 1,270 行、Resume 路由 1,187 行。拆分依据是下节事务与用例边界。 |
| P1 | 恢复一致性和跨域写入 | 备份主库和文件分时，Hub/产物另存，移动回执独立；恢复路由只重建 Career。旧 Agent 的 Focus 活动需同事务保留。助手唯一决策记录与跨域目标写入之间存在并发及崩溃窗口，待故障注入复现。 [数据所有权](data-ownership.md) |
| P1 | Provider 和协议泄入工作流用例 | Workflow 组装具体 Harness，Worker 做类型检查，控制 Router 知道原生协议路径；ModelGateway 引用助手/简历验证。 [Workflow](../../app/workflow.py) [Worker](../../app/workflow_worker.py) [Gateway](../../app/model_gateway.py) |
| P2 | 内容链接解析反向引用、旧兼容表现层跨域 | Markdown 渲染在函数内导入 KnowledgeStore；日常和 AI 首页分别直接调用旧 Router 作为回退。 [依赖图](dependency-map.md) |

## C. 建议、风险与验收

| 建议 | 当前实现与问题 | 目标与涉及文件 | 风险 / 预计收益 | 验收 |
| --- | --- | --- | --- | --- |
| 先抽出 Bootstrap | 两个工厂承担构造、迁移及安全装配，桌面再承担任务和中间件；恢复后替换单个 state 引用。 | `main.py`、`mobile_main.py`、`database.py` 按容器、迁移编排和 Lifespan 分阶段抽取；工厂签名保留。API 通过具名依赖取用例。 | 高。顺序、历史迁移和旧入口易受影响；启动失败可定位到阶段，测试可直接替换服务。 | 工厂 import 无 I/O；路由/method/name 和 schema/迁移版本相等；空库、旧库、失败回滚、取消回收可复测。 |
| 将全来源扫描退出写请求热路径 | 桌面中间件重读所有来源，移动和部分桌面路由已能单条 upsert。旧快照并发写可能覆盖较新投影，需要验证。 | `main.py`、`search.py`、Workspace/知识/求职/视频写入与 MobileCaptureService。提交后发出包含 kind、ID、Revision 的本地变化通知；删除发墓碑，合并重复键；只有对应投影重新读取。保留启动/手工对账并覆盖 Obsidian 外部变化。 | 中高。删除、归档、隐私筛选及并发乱序最敏感；预计减少磁盘读、重复解析和写请求延迟，需采样再量化。 | 用 fixture 断言一次无关写零扫描、单实体只投影一次；验证删除、乱序、重复、失败后重建及桌面/手机并发。FTS5、结果和 URL 保持。 |
| 监督器与注册拆开 | 启动器、安装校验、进程、Worker 与健康探针嵌套；丢日志并固定重试。 | `plugins.py`、`plugin_runtime.py`、`install_plugins.py`、`plugin_web.py`、`runtime.py`。Feature Registry 只负责静态装配；Integration Adapter 自管配置、协议与探针；Process Supervisor 管进程退出、退避上限、诊断及停止。 | 高。重复 Worker、关闭竞态和敏感日志；预期单插件故障可见且可恢复。 | 模拟 spawn 错误、非零退出、启动超时和人工停止；断言停止后不再重启、两插件独立、锁争用安全、日志限长/脱敏且无凭据。 |
| 分切 Career 与简历 | 一套 Repository 兼顾档案、附件、岗位、技能、路线和简历；两 Router 做大量用例编排。 | `career.py`、`routers/career_learning.py`、`routers/resumes.py`、`resume_*.py`。依次抽档案/证据、投递、简历编辑/定制/导入导出、学习；保留事务及迁移标识。 | 高。快照、照片、Revision 和模型确认易回归；用例可分别演进。 | POST/PATCH、阶段历史、附件、旧链接、源简历保护和快照完整性测试保持；新增的切片依赖测试逐步启用。 |
| 分切 Income | 单一 Repository 处理现金账本、首品销售验证和机会证据/复盘。 | `income.py`、`routers/income.py`。先抽金额及证据纯规则，再分账本、产品验证、机会复盘服务；历史兼容迁移留在现有序列。 | 高。现金净值、证据冻结和跨切片验证容易被拆断；规则可独立验证。 | 验证整分、退款、首单、证据与归档冻结；保留历史迁移、表及 HTTP 契约。 |
| 拆分系统运维与内容 API | `routers/system.py` 同时处理材料、搜索、回收站、Obsidian、移动、备份与运行状态。 | 按[文件映射](target-architecture.md)迁移；备份恢复保留隔离预演，设计显式停写/重新装配和多源恢复清单。 | 中高。Route name、模板与恢复过程影响多个模块；降低运维和业务变更的相互影响。 | 隔离恢复演练核对主库、Hub、候选、私有回答、照片和设备同步；缺失件可见，恢复前后禁止自动重复外发。 |
| 收敛工作流执行端口 | Worker 与 Gateway 识别具体 Harness，审批事务与外部派发/文件由恢复逻辑衔接。 | `workflow*.py`、`routers/workflow.py`、`model_gateway.py`、`deepseek_harness.py`，按预览批准、派发、执行、恢复、投影建立明确输入输出。 | 高。批准绕过、重复调用、过期卡片；收益为后端可替换、失败状态可测试。 | 重复领取/ACK 丢失、停机恢复、未知结果重审、文字决策引用、同源 SSE、私有字段投影均通过；固定上游协议保持。 |

## D. 重构顺序

按[路线图](refactoring-roadmap.md)实施，先做 Task 02，随后推进进程/注册、检索和业务切片。本阶段只增加文档、扫描工具及架构测试。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 基线 Pytest | 311 通过。 |
| 最终 Pytest | 318 通过，包含 7 项新增架构检查、Playwright Chromium、真实 Autoloop 和本机 Harness；模型响应由回环测试服务提供。 |
| 静态与安全 | Ruff、Git 安全守卫、`git diff --check` 通过；关键模块覆盖率门槛为 80%，检查通过。 |
| 装配与兼容 | 工厂导入无数据目录写入；桌面 ASGI 启动和五个入口 HTTP 200；未启用移动服务返回 503。245 个桌面及 17 个移动路由/挂载项、SQLite schema 和迁移版本与起点一致。 |
| 仍需验证 | 未对真实数据、线上模型或 Android 实机执行操作。覆盖率运行仍报告 SQLite 连接未显式关闭的 `ResourceWarning`，已列入启动与数据访问后续检查。 |
