---
date: 2026-09-02
status: completed
type: feature
areas:
  - agent-runtime
  - tasks
  - local-search
interfaces:
  - GET /tasks
  - POST /tasks
  - GET /runs
  - GET /artifacts/{id}
data_migration: workspace.db agent_core v1 with pre-upgrade snapshot
compatibility: preserved
rollback: revert the Phase 1 commit and restore the automatic pre-migration snapshot when private task data must also be removed
verification:
  - agent core repository and lifecycle tests
  - desktop route rendering tests
  - full Pytest and Ruff
  - application import and Git security guard
commit: pending
---

# Agent Runtime Phase 1

## 背景与目标

工作台原有内容、知识、助手、学习和创作流程各自拥有任务语义，但缺少统一的项目、运行轨迹和产物登记。本批次先建立不依赖模型和外部服务的最小运行时，验证统一核心不会破坏现有领域边界。

## 最终行为

- 作者可以在 `/tasks` 创建项目和学习、研究、创作、构建四类任务。
- Chief 通过固定规则选择对应角色并生成三步执行计划。
- 本地运行只调用 FTS5 检索，最多读取八条摘要并生成私有任务工作纸。
- Reviewer 确认产物包含本地运行和非正式知识边界后，将运行置为待确认。
- 作者可以接受产物并完成任务，或取消运行；两种操作都不会修改知识卡、文章或外部系统。
- `/assistant` 的能力和行动白名单保持不变。

## 接口与数据

新增项目、任务、运行、步骤、工具调用和 Artifact 页面。`workspace.db` 新增 `agent_core` v1 迁移，正文产物存储在私有 `working/agent-artifacts/`，数据库只保存哈希、摘要和逻辑引用。

工具调用记录不保存完整查询正文。第一版不调用 `ModelGateway`，也没有后台调度、代码执行、网络工具或长期记忆。

## 兼容与回滚

现有随想、知识、助手、收入、求职、移动和公众号数据不迁移、不复制、不重写。Agent Core 使用独立迁移子系统和页面入口；回滚代码后旧页面仍可使用。若需要同时删除试验任务数据，应恢复升级前自动生成的私有数据库快照，而不是手工删除业务表。

## 验证结果

- 验证默认项目初始化和迁移幂等。
- 验证任务规划、本地执行、工具摘要、私有文件权限、人工接受和取消状态机。
- 验证任务、运行和产物页面以及 404 行为。
- 验证现有页面和静态资源继续渲染。

## 同步文档

- [本地任务运行时](../../features/agent-runtime.md)
- [系统架构](../../architecture/README.md)
- [存储架构](../../architecture/storage.md)
- [开发说明](../../development/README.md)
- [项目状态](../../../PROJECT_STATUS.md)
