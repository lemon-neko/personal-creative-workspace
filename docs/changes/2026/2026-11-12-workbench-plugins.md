---
date: 2026-11-12
status: completed
type: feature
areas:
  - desktop
  - plugins
  - ai-workflow
interfaces:
  - /
  - /tasks
  - /workflow
  - /legacy/planner
  - /legacy/tasks
data_migration: workspace workflow subsystem v1
compatibility: legacy routes and data preserved
rollback: disable desktop plugins and restart
verification:
  - workspace approval, deduplication and CSRF tests
  - pinned Autoloop engine with isolated synthetic gateway
  - pinned Super Productivity Web build and browser validation
commit: pending
---

## 桌面工作台插件

原版 Super Productivity Web 提供日常工作和月历。固定版本的 Autoloop 提供原生派发、执行时间线和决策卡片。内置插件注册表统一装配桌面导航和业务路由。

任务菜单只交接选中的任务 ID 和标题。每轮调用模型前均须预览并确认，验收记录与产物由工作台维护。旧待办、阶段行动、执行记录及移动网关继续使用原有数据。插件关闭后主入口回到旧界面。

操作及恢复参见 [用户指南](../../guides/workbench-plugins.md) 与 [运行文档](../../operations/workbench-plugins.md)。

## 验证结果

完整 Pytest 299 项通过，包含固定版本 Autoloop 的独立引擎验收。Ruff、应用导入和安全守卫通过。Chrome 隔离环境验证了默认空白月历、键盘录入、拖拽与计时、任务菜单、回答续跑、人工验收、刷新保留和窄屏。模型输出使用虚构测试材料。
