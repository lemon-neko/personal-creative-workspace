---
date: 2026-08-28
status: completed
type: refactor
areas:
  - career-learning
  - frontend
interfaces:
  - GET /learning/history
  - GET /learning/maintenance
  - POST /learning/stages/{stage_id}/status
data_migration: none
compatibility: preserved
rollback: revert this feature batch; no database rollback is required
verification:
  - targeted career and application tests
  - full pytest and ruff
  - application import and security guard
commit: pending
---

# 学习路线极简化

## 背景与目标

旧页面同时展示八层工程框架、四阶段时间线和四套大型证据表单，主线重复且难以扫描。本次将默认学习页收敛为一张五层能力路线，只回答当前层级、下一步和最终能力链。

## 最终行为

- `/learning` 只展示工程底座、最小 Agent、可靠 Runtime、状态化编排和产品化交付。
- 每层直接展示能力链、产出、参考项目和紧凑状态控件。
- 主页面不再出现 Commit、测试结果和私人复盘输入框。
- `/learning/history` 只读展示已有阶段证据、归档研读路线和历史战役。
- `/learning/maintenance` 承担技能与额外任务维护。
- 页面保持单列、平面、无阴影结构，手机端沿相同顺序展示。

## 接口与数据

新增状态专用接口 `POST /learning/stages/{stage_id}/status`，只更新 `status` 和更新时间，不读取或覆盖 Commit、测试结果及复盘。现有完整阶段更新接口继续兼容旧调用。

本次不修改数据库结构，也不迁移私人数据。

## 兼容与回滚

现有路线、阶段、参考仓库、Commit、测试结果、复盘和战役记录全部保留。旧 `show_archived` 查询跳转到独立历史页。回滚只需恢复模板、样式和路由代码，无需恢复数据库。

## 验证结果

- 验证主页面只存在一套五层能力路线。
- 验证状态更新不会清空历史证据。
- 验证历史与维护页面、移动布局和本地安全边界。
- 完整 Pytest：249 项通过。
- Ruff、应用导入和 Git 安全守卫通过。
- 本机工作台与 375px 窄屏人工验收通过。

## 同步文档

- [求职与学习](../../features/career-learning.md)
- [求职学习指南](../../guides/career-workflow.md)
