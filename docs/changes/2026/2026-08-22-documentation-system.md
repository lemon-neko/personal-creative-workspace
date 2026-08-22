---
date: 2026-08-22
status: completed
type: docs
areas:
  - documentation
  - tests
interfaces:
  - docs/features
  - docs/architecture
  - docs/guides
  - docs/operations
  - docs/development
  - docs/changes
data_migration: none
compatibility: application behavior and private data unchanged
rollback: revert this documentation batch
verification:
  - 197 pytest cases passed
  - Ruff passed
  - security guard passed
  - ASGI import passed
commit: pending
---

# 文档体系重构

## 背景与目标

原有功能、架构、使用、运行和安全信息集中在七篇不断增长的长文中，模块边界不够直接，也没有可持续的功能批次记录。本批次改为按功能模块存储，并建立公共架构、指南、运行、开发和更新档案目录。

## 最终行为

- 八个功能领域分别拥有独立说明，包括入口、流程、数据、模型、隐私、限制和测试。
- 内容模型成为随想、知识、文章、公众号和视频关系的权威来源。
- 根 README 只保留项目入口、安全摘要、快速启动和文档导航。
- 后续每个已完成的功能批次使用统一模板建立独立更新记录。
- 文档测试递归扫描全部 Markdown，并校验分类、链接、记录字段和敏感信息。

## 接口与数据

只调整仓库文档路径和文档测试，不修改应用路由、数据模型、私有 Vault、数据库或真实内容。

## 兼容与回滚

仓库内部链接全部更新到新目录。Git 历史保留旧文档；回滚可直接还原本批次文档和测试文件，无需数据恢复。

## 验证结果

- 文档结构、链接、标题、八个功能模块和更新记录 schema 通过递归文档测试。
- 完整 Pytest：197 项通过。
- Ruff、Git 安全守卫、ASGI 应用导入和 `git diff --check` 通过。

## 同步文档

- [文档首页](../../README.md)
- [功能模块](../../features/README.md)
- [开发说明](../../development/README.md)
- [更新档案](../README.md)
