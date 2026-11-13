---
date: 2026-11-12
status: completed
type: feature
areas:
  - workflow
  - observability
interfaces:
  - /tasks/matters
  - /tasks/sessions/{run_id}
  - /tasks/history
  - /tasks/rules
  - /workflow/control/matter
data_migration: none
compatibility: existing task, card, control stream and run URLs remain valid
rollback: revert the UI and read-model changes, then restart desktop; private telemetry can remain on disk
verification:
  - pinned Autoloop and real local Harness SDK with a synthetic loopback provider
  - browser workflow, real card follow-up, Fact replay, and narrow viewport
  - full Pytest, Ruff, import, and security guard
commit: pending
---

## AI 工作流可观测性 V3

控制中心以十二个环节展示来源、派发、执行、回执及后续动作。事项抽屉、独立轮次和 Session 页显示关联证据。终态轮次可按真实 Fact 序号回放，播放操作只在浏览器内改变可见状态。工作台继续沿用原有外发审批和原生卡片接口。

首次采集 Harness SDK 会话初始化与轮次结束信号。仅保存允许的字段，无数据库迁移。详情页区分 Autoloop 事实、本地结果与 Adapter 遥测。中间文本、工具、终端与文件变化没有可用的采集数据。

完整接口和能力矩阵见[可观测性审计](../../development/workflow-observability.md)。
