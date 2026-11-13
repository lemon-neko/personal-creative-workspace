---
date: 2026-11-11
status: completed
type: feature
areas:
  - workbench
  - focus
  - agent-runtime
interfaces:
  - GET /?day=YYYY-MM-DD
  - POST /today/events/{id}/slot
  - GET /tasks
data_migration: focus v4
compatibility: existing routes and deadlines preserved
rollback: revert the batch with the pre-upgrade snapshot after preserving newer writes
verification:
  - full Pytest and isolated Chromium calendar drag tests
commit: pending
---

## 日常工作与 AI 工作流窗口

### 背景与目标

把待办排程和 AI 跟进放在两个主入口。日历拖拽参考 [Super Productivity](https://super-productivity.com/use-cases/schedule-planner/)，决策暂停与继续参考 [agent-autoloop](https://github.com/KKKKhazix/agent-autoloop)。

### 最终行为

日常工作打开周日历和半小时时间轴。可以拖动或通过表单排程，查看开始与截止倒计时及当天活动。AI 工作流按下一步展示任务，支持确认后后台运行、决策后继续和人工验收。

### 接口与数据

`focus` v4 增加排程和活动记录。排程时间与截止日期独立。后台运行沿用原有任务状态与人工确认边界，服务重启时把中断的运行标为失败。

### 兼容与回滚

旧待办、原有业务页面和 AI 运行记录保留。旧列表通过「待办列表」进入。回退旧程序前先保全新写入，再使用升级前快照。

### 验证结果

使用虚构数据检查迁移回滚、排程持久化、隐私边界与后台运行中断恢复。完整 Pytest 297 项通过，浏览器覆盖跨日期拖拽、键盘安排和 320px 布局。

### 同步文档

- [日常工作与阶段行动](../../features/focus.md)
- [AI 工作流](../../features/agent-runtime.md)
- [存储结构](../../architecture/storage.md)
