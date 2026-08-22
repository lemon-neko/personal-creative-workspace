"""Dated, hand-curated career and open-source study snapshots.

This module is intentionally static. Importing or seeding it never visits a job
site, GitHub, or a model endpoint.
"""

from __future__ import annotations


BASELINE_VERSION = "2026-08-21-v1"
SNAPSHOT_DATE = "2026-08-21"

JOB_SNAPSHOTS = (
    {
        "id": "job-baseline-hikvision-app",
        "company": "海康威视",
        "title": "高级应用软件开发·大模型",
        "source_url": "https://talent.hikvision.com/home/socity/position?postId=B4F6AAF8C5C1FEB7D6C131231EBAB46F",
        "is_primary": 1,
        "capability_summary": "面向业务的大模型应用工程：Agent 编排、服务化、RAG、评测与稳定性。",
        "jd_text": "以大模型应用落地为主，关注 Agent 工程、检索增强、后端服务和生产可靠性。",
    },
    {
        "id": "job-baseline-hikvision-research",
        "company": "海康威视",
        "title": "大模型应用算法工程师",
        "source_url": "https://talent.hikvision.com/home/socity/position?postId=F3572C5AD0A1263CE644BEF27E2AA66F",
        "is_primary": 0,
        "capability_summary": "补充算法、检索、评测、数据闭环与效果优化能力。",
        "jd_text": "作为算法与评测参照，关注 RAG、模型效果评估、Badcase 和持续优化。",
    },
    {
        "id": "job-baseline-jd-ai-app",
        "company": "京东",
        "title": "软件开发岗（AI 应用方向）",
        "source_url": "https://zhaopin.jd.com/web/job-info-detail?requementId=220736",
        "is_primary": 0,
        "capability_summary": "补充通用 AI 应用工程、异步服务、数据库、缓存与交付能力。",
        "jd_text": "作为通用应用工程参照，关注 Python 服务、数据组件、工程质量和交付。",
    },
    {
        "id": "job-baseline-jd-agent-expert",
        "company": "京东",
        "title": "国际产研 AI Agent 算法/工程专家",
        "source_url": "https://zhaopin.jd.com/web/job-info-detail?requementId=219868",
        "is_primary": 0,
        "capability_summary": "补充前沿 Agent Runtime、协议、工具安全、沙箱和可观测能力。",
        "jd_text": "作为前沿 Agent 工程参照，关注 Runtime、MCP/A2A、工具治理与复杂系统稳定性。",
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

JOB_CAPABILITIES = {
    "job-baseline-hikvision-app": {
        "agent-runtime": "主岗位核心：Agent 编排、状态与失败恢复。",
        "rag-retrieval": "面向业务知识的检索增强。",
        "backend-services": "可维护的异步应用服务。",
        "eval-observability": "效果与稳定性必须能够验证。",
        "production-reliability": "生产交付、监控与降级。",
    },
    "job-baseline-hikvision-research": {
        "rag-retrieval": "重点补充检索、排序和算法效果。",
        "eval-observability": "重点补充数据评测与 Badcase 闭环。",
    },
    "job-baseline-jd-ai-app": {
        "backend-services": "通用软件工程和 AI 服务化。",
        "production-reliability": "工程质量、部署和稳定性。",
    },
    "job-baseline-jd-agent-expert": {
        "agent-runtime": "复杂 Agent Runtime 与 Harness。",
        "tools-security": "工具协议、权限、沙箱与人工审批。",
        "eval-observability": "Agent Trace、回放与评测。",
    },
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
