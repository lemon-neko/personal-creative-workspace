---
date: 2026-11-12
status: completed
type: feature
areas:
  - workflow
interfaces:
  - GET /tasks
  - GET /workflow/control/state
  - GET /workflow/control/stream
  - GET /workflow/control/runs/{run_id}
  - POST /workflow/cards/{card_id}/answer
  - POST /workflow/cards/{card_id}/resolve
data_migration: workflow v2 adds a private reply file marker
compatibility: existing daily, handoff, workflow items, rules, run and artifact links preserved
rollback: keep private reply files and the workspace database backup when reverting
verification:
  - Pytest, real Autoloop 1.8.1, Chromium desktop and narrow view
  - Ruff, application factory, security guard
commit: pending
---

## AI 工作流控制中心

四宫格改为状态栏、六阶段流程、事项、待决策、规则和历史。事实时间线区分事项与轮次，支持回执、定时复查、事件、卡片和人工续跑的追溯。断线时保留最后一次快照，用原生日志序号恢复。没有健康字段、用量或推荐理由时明确显示缺失。

控制操作保留原生接口，新增同源卡片回答和结案。工作台模型决策必须经外发预览和单次批准。文字回答的文件由工作台私有目录保存，Autoloop 只记录关联引用。没有修改日常工作、上游配置格式或 Hub 数据库。旧规则、工作项和运行链接继续可用。

真实引擎验证了暂停时拒绝立即运行、文字回答后的下一轮、回执的原子投影、取消、模型超时和重启恢复。浏览器使用隔离数据验证了实时更新、断线恢复、历史分页、普通 Ask、Notice、fyi、窄屏和键盘退出详情。自动测试覆盖了投影脱敏和文字回答保存失败回滚。

文档同步：[功能](../../features/workbench-plugins.md)、[指南](../../guides/workbench-plugins.md)、[架构](../../architecture/README.md)、[运维](../../operations/workbench-plugins.md)。
