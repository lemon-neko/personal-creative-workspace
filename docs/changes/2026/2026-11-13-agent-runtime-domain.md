---
date: 2026-11-13
status: completed
type: refactor
areas:
  - agent-runtime
interfaces:
  - legacy agent runtime facade and HTTP routes preserved
data_migration: none
compatibility: preserved
rollback: revert the Task 04 changes
verification:
  - agent runtime and existing workflow regression tests
  - browser acceptance
  - full Pytest, Ruff, application import and security guards
commit: pending
---

## Task 04 · Agent Runtime 领域拆分

## 背景与目标

旧 AgentCore 将项目、任务、运行、执行策略、存储和跨模块关联集中在一个仓储中。拆分后可独立验证运行规则和外部调用边界。

## 最终行为

旧任务、运行和验收操作保持原样。运行必须领取后才能执行；模型调用仍要预览确认。候选文件在读取和验收时校验 SHA-256，产物登记与运行状态一起提交。

## 接口与数据

原路由、表单、兼容 Facade 和 `app.state.agent_core` 保留。沿用 `agent_core` 版本 1–3、原表和私有文件目录。Autoloop 不受此拆分影响。

## 兼容与回滚

无迁移或数据搬运；撤回 Task 04 的代码即可回滚。已有任务、运行及产物链接继续可用。

## 验证结果

完整 Pytest 359 项通过，包含 Chromium 的旧任务创建、规划、本地执行、产物查看与人工验收，以及固定版本 Autoloop 和 DeepSeek Harness 的隔离回归。模型回归使用虚构数据和测试端点。Ruff、隔离数据根下的 FastAPI 导入、安全守卫及 `git diff --check` 均通过。

## 同步文档

[架构设计](../../architecture/agent-runtime.md) · [旧任务运行时](../../features/agent-runtime.md) · [数据所有权](../../architecture/data-ownership.md)
