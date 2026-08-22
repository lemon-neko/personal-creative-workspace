---
date: 2026-08-22
status: completed
type: docs
areas:
  - knowledge-obsidian
  - documentation
interfaces:
  - docs/architecture/private-vault-folders.md
data_migration: none
compatibility: existing Vault files and directories remain unchanged
rollback: revert this documentation batch
verification:
  - recursive documentation tests
  - private data guard
commit: pending
---

# 私有知识库目录说明

## 背景与目标

Obsidian 会直接展示 Vault 的物理目录，但仅凭目录名无法判断哪些是来源、正式知识、创作产物、生成索引或旧版兼容内容。本批次补充逐目录说明和手动操作边界。

## 最终行为

- 解释 `sources`、`knowledge`、`outputs` 的子目录和内容流向。
- 解释 `assets`、`archive`、`trash` 的生命周期和操作方式。
- 明确 `items` 是旧版兼容目录，只读兼容并等待显式迁移。
- 标明 `_templates`、`.obsidian`、`knowledge/indexes` 和 `知识首页.md` 属于模板、配置或可重建内容。
- 提供“新建、编辑、移动或删除”的安全操作矩阵和推荐 Obsidian 设置。

## 接口与数据

新增一份架构文档并接入文档、架构、知识功能和知识沉淀指南索引。应用接口、私有 Vault、数据库和真实内容均未修改。

## 兼容与回滚

无需迁移。文档明确保留旧 `items/` 的读取行为和现有迁移命令；回滚只需还原本批次文档与文档测试。

## 验证结果

- 目录名称和生命周期行为与当前代码及迁移实现逐项核对。
- 递归文档测试、安全守卫和链接检查通过。

## 同步文档

- [私有知识库目录说明](../../architecture/private-vault-folders.md)
- [架构入口](../../architecture/README.md)
- [知识库与 Obsidian](../../features/knowledge-obsidian.md)
- [知识沉淀指南](../../guides/knowledge-workflow.md)
