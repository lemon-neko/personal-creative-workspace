---
date: 2026-11-12
status: completed
type: refactor
areas:
  - daily-work
  - workflow
  - mobile
interfaces:
  - none
data_migration: none
compatibility: existing routes, enable flag, and package manifest preserved
rollback: revert the plugin startup refactor and restart the desktop service
verification:
  - corrupt Web and Autoloop packages and invalid Harness configuration
  - mobile snapshot authorization and existing workflow regressions
  - full Pytest, Ruff, application imports, and security guard
commit: pending
---

## 日常工作与 AI 插件故障隔离

日常工作页面和手机快照写入由独立路由维护。桌面进程分别校验、启动 Super Productivity Web 与 Autoloop，并沿用原插件开关、包清单和单进程锁。Web 包失效时首页提供旧待办入口。Autoloop 包或执行后端配置失效时，日常工作和手机快照可继续使用。

回归测试分别破坏两个包的校验值和 Harness 配置，验证未受影响的插件仍可启动。现有路由、审批、看板快照和数据格式保持兼容。

参见[系统架构](../../architecture/README.md)、[关键数据流](../../architecture/data-flows.md)和[桌面插件运维](../../operations/workbench-plugins.md)。
