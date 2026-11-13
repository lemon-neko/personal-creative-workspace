---
date: 2026-11-11
status: completed
type: feature
areas:
  - workbench
  - focus
  - frontend
interfaces:
  - GET /?board=upcoming
  - POST /today/events/{id}/today
  - existing daily event forms with optional date and inline editing
data_migration: none
compatibility: existing task, AI and workspace links preserved
rollback: revert this batch; existing tasks and deadlines are retained
verification:
  - full Pytest, including isolated task form and privacy tests
  - desktop and narrow Chromium acceptance
commit: pending
---

## 今日待办与安排交互

### 背景与目标

参考 [Super Productivity 的任务录入与展开操作](https://super-productivity.com/blog/getting-started-with-super-productivity/)，让今日列表可以直接操作任务，并把低频字段折叠在各自的入口。

### 最终行为

今日按逾期、未完成和已完成分组。按 Enter 连续录入，完成后可撤销；行末展开可改标题、日期和状态。待安排视图汇合未来及未排定的阶段行动，可放到今日。桌面主导航用线性图标区分页面，移动宽度保持简洁文字导航。

### 接口与数据

沿用 SQLite 的独立待办日期、阶段行动截止日期与今日重点。移入今日不会改阶段截止日期。局部 HTML 与整页表单复用同一服务端规则、CSRF 与可见性过滤；撤销检查当前状态。

### 兼容与回滚

没有迁移。既有待办、原行动、AI 交接与旧首页内容筛选链接继续可用。回退界面后，用户已保存的状态和日期仍保留。

### 验证结果

隔离数据覆盖日期安排、字段校验、完成撤销、过期写入、键盘与本机浏览器断线反馈；检查桌面及 320 px 窄屏布局。完整 Pytest 293 项通过，Ruff、应用导入和安全守卫通过。

### 同步文档

- [功能说明](../../features/focus.md)
- [操作指南](../../guides/focus-workflow.md)
- [架构说明](../../architecture/README.md)
