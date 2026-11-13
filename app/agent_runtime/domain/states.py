PROJECT_STATUSES = {"active", "paused", "archived"}
TASK_TYPES = {"learning", "research", "creation", "build"}
TASK_STATUSES = {
    "draft",
    "planned",
    "running",
    "reviewing",
    "completed",
    "failed",
    "cancelled",
}
RUN_STATUSES = {"planned", "running", "reviewing", "completed", "failed", "cancelled"}
STEP_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}
ARTIFACT_STATUSES = {"review", "accepted", "rejected"}
MAX_TITLE = 160
MAX_OBJECTIVE = 8_000
MAX_DESCRIPTION = 2_000
DEFAULT_PROJECT_ID = "project-personal-agent-team"


ROLE_DEFINITIONS = {
    "learning": ("learning", "学习", "从本地材料组织解释、练习与验收路径。"),
    "research": ("research", "研究", "整理来源、已知事实和仍需验证的问题。"),
    "creation": ("creator", "创作", "把已确认材料组织成可继续编辑的创作工作纸。"),
    "build": ("builder", "构建", "把工程目标整理成约束、步骤和验收清单。"),
}

TASK_TYPE_LABELS = {
    "learning": "学习",
    "research": "研究",
    "creation": "创作",
    "build": "构建",
}

TASK_STATUS_LABELS = {
    "draft": "待规划",
    "planned": "已规划",
    "running": "运行中",
    "reviewing": "待确认",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

RUN_STATUS_LABELS = {
    "planned": "已规划",
    "running": "运行中",
    "reviewing": "待确认",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "decision": "待决策",
    "resume": "待继续",
}
