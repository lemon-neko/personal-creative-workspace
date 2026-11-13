# Agent Runtime 领域架构

Task 04 将实验性的旧任务运行时拆成四个应用服务。日常主入口 `/tasks` 仍由 Autoloop 工作流负责；旧任务、步骤、决策和候选产物由本页所述运行时负责。两套运行 ID、表、调度和恢复逻辑独立。

```mermaid
flowchart LR
    HTTP["旧任务、运行、产物 HTTP"] --> Facade["AgentCoreRepository"]
    Container["AppContainer"] --> Facade
    Container --> Adapters["Search / ModelGateway 适配器"]
    Facade --> Services["Project / Task / Run / Artifact 服务"]
    Services --> Domain["实体、状态、规则"]
    Services --> Ports["应用端口"]
    Ports -. 实现 .-> UoW["SQLite Unit of Work"]
    Ports -. 实现 .-> Executors["LocalExecutor / ModelExecutor"]
    Ports -. 实现 .-> Files["ArtifactStorage"]
    UoW --> Repo["RuntimeRepository + FocusAdapter"]
    Repo --> DB[("workspace.db")]
    Executors --> Adapters
    Files --> Disk[("working/agent-artifacts/")]
    Autoloop["Autoloop · 独立调度和执行"] --> Gateway["ModelGateway"]
    Adapters --> Gateway
    Adapters --> Search["本地只读搜索"]
```

Domain 只依赖标准库和自身模型；应用层依赖端口，不执行 SQL、不处理 HTTP。组合入口注入 Search 和 Gateway；UoW 将 SQLite 仓储与 Focus 关联适配器绑定在同一连接。阶段行动与日常事件各有独立关联表，重复交接复用已有任务，只记录一次 Focus 活动。仅详情可见的任务不会出现在总览或模型预览中。

```mermaid
erDiagram
    WorkspaceProject ||--o{ WorkspaceTask : owns
    WorkspaceTask ||--o{ AgentRun : plans
    AgentRun ||--o{ AgentStep : contains
    AgentStep ||--o{ ToolCall : records
    AgentRun ||--o{ Artifact : produces
    WorkspaceTask ||--o{ Artifact : tracks
    AgentRun ||--o| Decision : requests
    WorkspaceTask ||--o| SourceLink : refers_to
```

`SourceLink` 表示可选的阶段行动或日常事件关联；`Decision` 是既有的每轮最多一条决策记录。项目、任务、运行、步骤、工具摘要和产物元数据继续使用 `workspace.db` 中的 `agent_core` 版本 1–3，无新增迁移。产物正文仍位于私有数据根的 `working/agent-artifacts/`，目录和文件权限分别为 `0700` 和 `0600`。

```mermaid
stateDiagram-v2
    [*] --> planned
    planned --> running: 领取计划
    running --> planned: 暂停等待决策
    planned --> planned: 保存选择并更新 Revision
    running --> reviewing: 候选与运行状态一起提交
    reviewing --> completed: 人工验收
    running --> failed: 执行失败或启动恢复
    planned --> cancelled: 取消
    reviewing --> cancelled: 取消并拒绝候选
```

任务从 `draft` 起步，随当前运行进入 `planned / running / reviewing / completed`，异常进入 `failed / cancelled`。失败或取消后可建新运行；重复规划复用已有的未执行计划。旧运行保留。正在执行的运行不能用普通取消接口终止；启动恢复只把遗留的 `running` 标记为 `failed`（`error_code=interrupted`），不会重新调用模型。产物从 `review` 转为 `accepted` 或 `rejected`。

```mermaid
sequenceDiagram
    actor User as 用户
    participant HTTP as 旧运行页面
    participant Run as RunService
    participant DB as SQLite UoW
    participant Exec as 执行器
    participant File as 私有文件
    User->>HTTP: 运行本地计划 / 确认预览
    HTTP->>Run: 运行 ID / 模型预览指纹
    Run->>DB: 校验当前状态、决策、Revision；领取
    DB-->>Run: 提交并释放事务
    Run->>Exec: 执行本地检索或经 Gateway 调用模型
    alt 模型提出问题
        Run->>DB: 保存选项并返回 planned
        User->>HTTP: 保存选择并重新确认新预览
    else 生成候选产物
        Run->>File: 加锁并原子写入，计算 SHA-256
        Run->>DB: 提交产物元数据、步骤、任务和运行状态
        User->>HTTP: 人工验收
        Run->>File: 校验正文 SHA-256
        Run->>DB: 核对状态，提交验收
    end
```

| 策略 | 输入、输出和限制 |
| --- | --- |
| LocalExecutor | 用任务目标检索，必要时用标题再查；最多取 8 条，生成规则工作纸并执行确定性检查。工具记录只含计数。不调用模型或写入正式知识库。 |
| ModelExecutor | 预览包含指令、标题、目标、角色和已回答的决策。确认时按当前 Revision、模型配置与实际材料重算指纹，并校验输入上限。执行经现有 Gateway 限制输出和记账，只接受候选稿或单条决策；不新增工具、命令、文件修改或发布权限。 |

写事务用 `BEGIN IMMEDIATE`。创建任务与关联及活动一起提交；领取在同一事务校验 Revision、决策和状态；回答与任务 Revision 一起更新。模型和本地检索都在事务外运行。文件先原子写入，随后将产物登记和运行状态一起提交；事务失败会删除本次文件。验收读取并校验文件后，在写事务中复核登记和运行状态。

原有路由、表单、`app.agent_core` 公共实体、`AgentCoreRepository` 与 `request.app.state.agent_core` 保留。旧进程内调用可继续注入已有的本地结果或执行回调；HTTP 模型入口只走带指纹的确认方法。此次回退只需撤回 Task 04 的代码变更。

验证覆盖旧版升级与回滚、并发领取、预览过期与 Token 上限、决策续跑、私有过滤、故障回滚、中断恢复、产物验收和浏览器旧页面流程。完整检查结果见[变更记录](../changes/2026/2026-11-13-agent-runtime-domain.md)。

SQLite 与文件系统没有跨介质事务。进程若在文件写入后、SQLite 提交前被强制终止，可能留下未登记的私有文件；当前没有自动扫描删除。标准加密备份仍不包含候选正文。旧运行时仍只支持单个决策；统一两套运行协议、调度和数据不在本次范围。
