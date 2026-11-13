---
date: 2026-11-12
status: completed
type: feature
areas:
  - workflow
  - model-gateway
interfaces:
  - none
data_migration: none
compatibility: existing rules, workbench approvals and old item links preserved
rollback: remove the private Harness setting and restart to use the default gateway
verification:
  - real Autoloop and DeepSeek Harness with two approved requests
  - isolated tests for the provider request, archive and existing workflow
  - Ruff, application factory and security guard
commit: pending
---

## DeepSeek Harness 调度与归档

AI 工作流可通过 Autoloop 和本机 DeepSeek Harness 处理任务。规则触发后等待工作台确认，Harness 每轮通过受限的本机端点请求 DeepSeek API，产物和待决策问题沿现有流程回写。模型用量随原生回执记录。旧事项通过独立归档边界移出当前工作列表，历史链接和本机数据仍可查看。

以虚构任务完成真实规则触发、审批、Ask、人工答复、下一轮调度、模型用量回执和产物验收。隔离测试覆盖了预览外发范围与归档后重新交接。真实 Cron 验证了定时事件能被领取并生成待确认卡片。

文档同步：[功能](../../features/workbench-plugins.md)、[指南](../../guides/workbench-plugins.md)、[架构](../../architecture/README.md)、[运维](../../operations/workbench-plugins.md)。
