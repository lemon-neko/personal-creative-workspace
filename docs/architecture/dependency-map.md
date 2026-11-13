# 依赖图

基线 `6a8375e`。用 [AST 扫描器](../../tools/architecture_audit.py)读取 `app/` 的 70 个 Python 模块，得到 238 条去重的内部导入边。函数内导入计入源码依赖。静态分析未推断 `app.state`、字符串入口、动态导入、SQL 或远端请求，图 B、C 中这些边由调用链补充。全量逐文件边见[模块清单](module-map.md)；三图按阅读范围合并节点。

```bash
.venv/bin/python tools/architecture_audit.py
.venv/bin/python tools/architecture_audit.py --format json
```

图中实线为常规调用或导入，点线为跨域或反向依赖，标注「基础设施」的节点为多个领域共用，外部进程和存储单独画出。

## A. 全局模块依赖

```mermaid
flowchart LR
    Entry["ASGI 入口"] --> Factory["main / mobile_main"]
    Factory --> Routes["bootstrap.routes"]
    Routes --> Registry["plugins · 静态元数据"]
    Routes --> Routers["13 个桌面 Router"]
    Registry --> Paths["plugin_paths · 固定源与目录"]
    Factory --> Work["业务服务与 Repository"]
    Factory --> Runtime["Lifespan → plugin_runtime"]
    Routers --> Work
    Routers --> Web["web / Jinja · 基础设施"]
    Web --> Privacy["privacy · 基础设施"]
    Privacy --> Paths
    Work --> DB["database / SQLite · 基础设施"]
    Work --> FS["atomic / 私有文件 · 基础设施"]
    Work --> Index["SearchRepository"]
    Work --> Model["ModelGateway"]
    Model -. "导入助手及简历校验" .-> Work
    Model --> Provider["llm / deepseek_harness"]
    Runtime --> Supervisor["process_supervisor"]
    Runtime --> Hub["Autoloop 适配器 → workflow_hub"]
    Runtime --> Packages["plugin_packages"]
    Packages --> Registry
    Work --> Paths
```

Task 01 记录 52 条循环边。Task 05 拆开静态注册、源与目录和 Router 装配后，当前只剩 `content → knowledge_store → content/workspace → content` 的 4 条循环边，回边在 Markdown 链接改写函数内。精确边集由[循环基线](../../tests/architecture/legacy_cycles.txt)锁定。

## B. 业务领域依赖

```mermaid
flowchart LR
    Daily["日常工作"] --> SP["外部 Super Productivity"]
    Daily -. "旧视图回退" .-> Focus["阶段行动 / 旧排期"]
    Daily --> Mobile["移动只读快照与随想"]
    SP -->|"所选 ID / 标题"| Workflow["AI 工作流"]
    Workflow -. "禁用时回退" .-> Legacy["旧 Agent"]
    Legacy -. "Focus 适配器；同事务写活动" .-> Focus
    Assistant["决策助手"] -. "读取摘要 / 确认后建学习任务" .-> Career["Career / 简历 / 学习"]
    Assistant -. "阶段摘要" .-> Focus
    Assistant -. "确认后建随想" .-> Vault["Vault 内容 / 知识"]
    Mobile -->|"幂等写随想"| Vault
    Create["创作 / 发布 / 视频"] -->|"文章、图片、Revision"| Vault
    Search["搜索 · 基础设施"] -. "读取投影" .-> Career
    Search -. "读取投影" .-> Vault
    Search -. "读取投影" .-> Create
    Mobile -. "尽力更新单条索引" .-> Search
    Workflow --> Gateway["模型网关 · 基础设施"]
    Legacy --> Gateway
    Legacy --> Search
    Assistant --> Gateway
    Career --> Gateway
    Vault --> Gateway
    Create --> Gateway
    Gateway -. "任务输出校验回引" .-> Assistant
    Gateway -. "候选简历校验回引" .-> Career
    Income["收入"] --> DB["共享 SQLite · 基础设施"]
    Career --> DB
    Focus --> DB
    Workflow --> DB
```

Assistant 到 Career 的写边来自路由中的确认用例。旧 Agent 通过 [Agent Runtime 的 Focus 适配器](agent-runtime.md) 读取可见性和记录交接活动。模型网关回边表示静态导入，业务侧正向箭头多为实际调用，不能据此直接推断新的 Python import 循环。 `router → request.app.state.*` 由组合入口注入，其中 `/settings/backups/restore` 会在恢复后替换 Career 引用。

## C. 应用启动与外部进程

```mermaid
flowchart LR
    Launch["launchd 或 CLI"] --> ASGI["桌面 Uvicorn / asgi"]
    ASGI --> Factory["create_app · 私有根、两库注册、构造、seed、装配"]
    Factory --> Life["lifespan · 旧运行恢复、全来源索引、周回顾"]
    Life --> Lock["worker.lock"]
    Lock --> WebCheck["Web Supervisor：包校验与签名探针"]
    Lock --> HubCheck["Hub Supervisor：验包、配置与认证探针"]
    WebCheck --> Web["Python plugin_web · localhost:8767"]
    HubCheck --> Hub["Node Autoloop up · 127.0.0.1:8768"]
    Hub -->|"首次认证探针通过"| Worker["独立监督的 WorkflowWorker"]
    Worker <-->|"回环 HTTP"| Hub
    Worker --> Gateway["ModelGateway"]
    Gateway --> Harness["可选 dsh 子进程 / stdio"]
    Harness -->|"单次本机请求代理"| Gateway
    Gateway --> External["经审批的模型端点"]
    Browser["桌面浏览器"] -->|"8765"| ASGI
    Browser -->|"iframe / 浏览器存储"| Web
    Launch --> Mobile["独立移动 Uvicorn · 127.0.0.1:8766"]
    Phone["Android PWA"] --> Tailnet["Tailscale Serve"]
    Tailnet --> Mobile
    Mobile --> Store["私有 Vault / mobile.db / FTS"]
    Factory --> Store
```

桌面 Lifespan 持有独占锁。Web 与 Hub 各自验包、探测、回收和退避。Hub 首次健康后启动 Worker，Worker 首次完成认证领取轮询后报告就绪。实现、状态机与回归见[插件运行时](plugin-runtime.md)。
