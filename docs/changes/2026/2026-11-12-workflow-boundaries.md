---
date: 2026-11-12
status: completed
type: refactor
areas:
  - workflow
  - architecture
interfaces:
  - none
data_migration: none
compatibility: existing routes, approval fingerprints, and private files preserved
rollback: revert the workflow refactor without restoring data
verification:
  - workflow baseline, Autoloop integration, and local Harness tests
  - dispatch retry, receipt recovery, and stream projection regression tests
  - full Pytest, Ruff, application import, and security guard
commit: pending
---

## AI 工作流模块边界

工作流预览和审批集中在应用服务。工作项、轮次状态及私有产物由存储模块管理。Autoloop 客户端管理凭据、HTTP 与上游事实流，Worker 负责派发、领取和回执，插件运行管理负责进程与重启恢复。控制中心使用同源的只读投影。

沿用已有工作流表、审批指纹、路由和私有文件。回归测试模拟派发确认和结果确认丢失，验证同一审批事件可重送，已保存的结果可补回执，恢复时不会重跑模型。实时流测试覆盖游标与内部字段过滤。

参见[系统架构](../../architecture/README.md)和[关键数据流](../../architecture/data-flows.md)。
