"""Dated, hand-curated open-source study material.

This module is intentionally static. Importing or seeding it never visits a job
site, GitHub, or a model endpoint.
"""

from __future__ import annotations


BASELINE_VERSION = "2026-08-28-v2"
SNAPSHOT_DATE = "2026-08-21"

AGENT_ENGINEERING_LAYERS = (
    {
        "order": 1,
        "title": "软件工程基础",
        "summary": "API、数据库、Redis、消息队列、并发、Docker、日志与系统设计。",
        "stage_label": "已有底座",
    },
    {
        "order": 2,
        "title": "Model",
        "summary": "模型调用、推理边界、结构化输入输出与失败处理。",
        "stage_label": "阶段 1",
    },
    {
        "order": 3,
        "title": "Context",
        "summary": "Prompt、History、RAG、Memory、State 与 Tool Result。",
        "stage_label": "阶段 1、4",
    },
    {
        "order": 4,
        "title": "Agent Runtime",
        "summary": "Loop、Planning、Retry、Checkpoint、Recovery 与停止条件。",
        "stage_label": "阶段 1—3",
    },
    {
        "order": 5,
        "title": "Action",
        "summary": "Tool、MCP、权限、Sandbox 与人工审批。",
        "stage_label": "阶段 1、2、4",
    },
    {
        "order": 6,
        "title": "Orchestration",
        "summary": "Workflow、StateGraph、Multi-Agent 与 Durable Execution。",
        "stage_label": "阶段 3、4",
    },
    {
        "order": 7,
        "title": "Production & Quality",
        "summary": "Eval、Trace、Replay、安全、成本、延迟与监控。",
        "stage_label": "阶段 2—4",
    },
    {
        "order": 8,
        "title": "Application",
        "summary": "把能力交付为 Web、App、CLI、API 与实际业务应用。",
        "stage_label": "贯穿全程",
    },
)

LEARNING_PATH = {
    "id": "agent-application-engineering",
    "title": "Agent 应用开发路线",
    "summary": "从手写最小循环开始，逐步掌握 Runtime、LangGraph 与产品化能力。",
    "source_title": "Agent 工程通用能力",
}

LEARNING_STAGES = (
    {
        "id": "agent-path-minimal-agent",
        "order": 1,
        "title": "手写最小 Agent",
        "objective": "不用框架理解 Agent 最小闭环和所有停止边界。",
        "focus": "Model、Context、Tool Call、Observation、State、停止条件。",
        "deliverable": "假模型、两个受限工具、最大步数、超时、完整轨迹及单元测试。",
        "acceptance_command": "pytest -q",
        "capabilities": ("agent-runtime", "backend-services", "eval-observability"),
        "references": (),
    },
    {
        "id": "agent-path-openhands",
        "order": 2,
        "title": "拆 OpenHands",
        "objective": "理解 Agent Loop 与受控执行环境如何共同组成 Runtime。",
        "focus": "Agent Loop、Runtime、Sandbox、权限、持久化与 Trace。",
        "deliverable": "受限工具 Runtime、人工审批和可回放轨迹。",
        "acceptance_command": "pytest -q",
        "capabilities": ("agent-runtime", "tools-security", "eval-observability"),
        "references": (
            {
                "id": "stage-openhands",
                "name": "OpenHands",
                "repo_url": "https://github.com/OpenHands/OpenHands",
                "role": "主参考",
                "target_modules": "Agent Loop、Runtime、Sandbox/工具边界、事件与 Trace、审批和测试。",
            },
        ),
    },
    {
        "id": "agent-path-langgraph",
        "order": 3,
        "title": "学 LangGraph",
        "objective": "把状态、流程、持久化和人工介入组织成可恢复工作流。",
        "focus": "State、Node、Edge、Checkpoint、Persistence 与 HITL。",
        "deliverable": "可暂停、恢复并持久化状态的工作流。",
        "acceptance_command": "pytest -q",
        "capabilities": ("agent-runtime", "backend-services", "production-reliability"),
        "references": (
            {
                "id": "stage-langgraph",
                "name": "LangGraph",
                "repo_url": "https://github.com/langchain-ai/langgraph",
                "role": "主参考",
                "target_modules": "StateGraph、Checkpoint、Persistence、HITL、Durable Execution 与测试。",
            },
        ),
    },
    {
        "id": "agent-path-productization",
        "order": 4,
        "title": "看框架与产品化",
        "objective": "建立框架对照视角，并把工具协议、安全边界接回自己的项目。",
        "focus": "Memory、RAG、MCP、Skills、Multi-Agent、Eval 与平台能力。",
        "deliverable": "架构对照笔记，并将 MCP 工具注册和权限层接入第三阶段项目。",
        "acceptance_command": "pytest -q",
        "capabilities": ("rag-retrieval", "tools-security", "eval-observability", "production-reliability"),
        "references": (
            {
                "id": "stage-agentscope",
                "name": "AgentScope",
                "repo_url": "https://github.com/agentscope-ai/agentscope",
                "role": "框架参照",
                "target_modules": "Agent/Message 抽象、Memory、Tool、Multi-Agent、Tracing 与评测。",
            },
            {
                "id": "stage-dify",
                "name": "Dify",
                "repo_url": "https://github.com/langgenius/dify",
                "role": "产品化参照",
                "target_modules": "Workflow、模型管理、插件、Sandbox、RAG 与可观测分层。",
            },
        ),
    },
)

CAPABILITY_DOMAINS = (
    ("agent-runtime", "Agent 编排与运行时", "P0", "状态、记忆、Harness、失败恢复与可暂停执行。", 1),
    ("rag-retrieval", "RAG 与检索", "P1", "Embedding、混合检索、重排与向量数据库。", 2),
    ("backend-services", "AI 后端服务", "P0", "Python、FastAPI、异步接口、数据库、缓存和消息队列。", 3),
    ("tools-security", "工具协议与安全", "P1", "MCP、A2A/A2UI、工具权限、沙箱和人工审批。", 4),
    ("eval-observability", "评测与可观测", "P0", "Eval、Trace、Badcase、回放、A/B 测试和数据飞轮。", 5),
    ("production-reliability", "生产可靠性", "P0", "Docker/K8s、CI/CD、限流、熔断、降级、监控和脱敏。", 6),
)

CAPABILITY_SKILL_NAMES = {
    "agent-runtime": ("Agent 编排与状态管理",),
    "rag-retrieval": ("LLM Agent 与 RAG", "PostgreSQL 与 pgvector"),
    "backend-services": ("Python 工程", "FastAPI 服务化", "Redis 与异步任务"),
    "tools-security": ("MCP 与工具调用", "Agent 安全与权限"),
    "eval-observability": ("Agent 评测与可观测性",),
    "production-reliability": ("Docker 与运行部署",),
}

REFERENCE_PROJECTS = (
    {
        "id": "open-deep-research",
        "name": "Open Deep Research",
        "repo_url": "https://github.com/langchain-ai/open_deep_research",
        "week": 1,
        "study_focus": "LangGraph 状态、规划、执行、反思、结构化输出和 MCP。",
        "target_modules": "入口图、状态定义、规划/研究节点、模型与 MCP 配置、测试。",
        "deliverable": "可暂停恢复的最小 Agent，包含假模型和状态流测试。",
        "acceptance_command": "pytest -q",
        "capabilities": ("agent-runtime", "tools-security"),
        "skill": "Agent 编排与状态管理",
    },
    {
        "id": "langgraph-fastapi-starter",
        "name": "LangGraph FastAPI Starter",
        "repo_url": "https://github.com/IgnazioDS/langgraph-fastapi-starter",
        "week": 2,
        "study_focus": "FastAPI、SSE、Pydantic、SQLAlchemy、Alembic、PostgreSQL/pgvector。",
        "target_modules": "API 路由、SSE 事件、会话模型、迁移、持久化与引用投影。",
        "deliverable": "带会话、流式事件、持久化和引用的 Agent API。",
        "acceptance_command": "pytest -q",
        "capabilities": ("backend-services", "rag-retrieval"),
        "skill": "FastAPI 服务化",
    },
    {
        "id": "onyx",
        "name": "Onyx",
        "repo_url": "https://github.com/onyx-dot-app/onyx",
        "week": 3,
        "study_focus": "文档摄取、Celery、Redis、幂等重试和检索 Worker。",
        "target_modules": "Connector/ingestion、后台任务、检索流水线、重试与状态记录。",
        "deliverable": "异步文档入库、混合检索与失败恢复小实验。",
        "acceptance_command": "pytest -q",
        "capabilities": ("rag-retrieval", "backend-services", "production-reliability"),
        "skill": "Redis 与异步任务",
    },
    {
        "id": "openhands",
        "name": "OpenHands",
        "repo_url": "https://github.com/OpenHands/OpenHands",
        "week": 4,
        "study_focus": "Runtime、工具沙箱、审批、Trace 和 React Agent UI。",
        "target_modules": "Runtime 边界、工具动作、审批状态、事件流、轨迹与前端投影。",
        "deliverable": "受限工具调用、人工审批、轨迹回放与最小前端。",
        "acceptance_command": "pytest -q",
        "capabilities": ("agent-runtime", "tools-security", "eval-observability"),
        "skill": "Agent 安全与权限",
    },
    {
        "id": "dify",
        "name": "Dify（扩展阅读）",
        "repo_url": "https://github.com/langgenius/dify",
        "week": 0,
        "study_focus": "只研究工作流引擎、插件与 Sandbox 分层。",
        "target_modules": "工作流调度、插件协议、Sandbox 边界。",
        "deliverable": "一页架构笔记；不安排整体复刻。",
        "acceptance_command": "无需验收命令",
        "capabilities": ("agent-runtime", "tools-security"),
        "skill": "MCP 与工具调用",
        "is_optional": 1,
    },
)
