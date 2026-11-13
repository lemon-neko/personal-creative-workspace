---
date: 2026-11-12
status: completed
type: docs
areas:
  - architecture
  - storage
  - development
interfaces:
  - none
data_migration: none
compatibility: preserved
rollback: revert documentation edits
verification:
  - compare code, plugin versions, and storage paths
  - verify the local desktop and daily-work endpoints
  - documentation tests and security guard
commit: pending
---

## 当前架构与数据流盘点

整理桌面、移动、Obsidian、Super Productivity、Autoloop 和 DeepSeek Harness 的运行拓扑及技术栈。将当前工作流、旧任务运行时和规则周回顾分开描述。补充工作流审批、单轮模型请求、产物验收、内容同步、权威存储和备份边界。同步旧待办与阶段行动的页面入口。

本次只更新文档。对照了应用工厂、内置插件注册、工作流桥接、模型适配器和备份代码，并确认本机工作台与日常工作入口可用。文档入口为[系统架构](../../architecture/README.md)、[关键数据流](../../architecture/data-flows.md)和[存储架构](../../architecture/storage.md)。
