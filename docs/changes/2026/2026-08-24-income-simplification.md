---
date: 2026-08-24
status: completed
type: refactor
areas:
  - income
  - assistant
  - search
interfaces:
  - /income
  - /income/entries
data_migration: workspace.db bounty_income v3 cleanup and income v1, with pre-upgrade snapshot
compatibility: private content and non-income modules remain unchanged; removed business URLs now return 404
rollback: restore the pre-migration database snapshot and revert this feature batch
verification:
  - tests/test_income.py
  - full pytest and ruff
  - application import, docs and security guard
commit: pending
---

# 收入面板极简重构

## 背景与目标

旧商业系统同时管理公开扫描、需求信号、机会评分、产品实验、七日复盘和悬赏，超过当前实际需要。本批次将收入控制面收敛为四个固定方向和一份手工确认账本。

## 最终行为

`/income` 只显示实际到账、本月到账、待到账、净现金、十二个月趋势、来源分布、最近记录和四张来源卡。数字产品固定排在第一位；情报订阅、Micro-SaaS、广告与 CPS 作为可选方向保留。

新增收支默认待确认。只有已确认收入会进入实际到账，费用和退款会降低净现金，作废记录不参与统计。页面加载和保存不联网、不调用模型、不自动发布或收款。

## 接口与数据

保留 `/income`，新增 `/income/entries` 及收支确认、作废和来源编辑表单。`workspace.db` 新增 `income_sources` 和 `income_entries`；金额统一使用人民币分。

旧信号、机会、实验、指标、悬赏、发现设置及其路由和运行时代码已移除。助手只读取脱敏收入汇总，搜索和 Android PWA 不接入收入明细。

## 兼容与回滚

迁移前自动建立数据库快照。旧业务表在同一事务中删除，迁移失败会回滚表结构和版本；需要整体回退时，停止应用后恢复迁移前快照并切回旧代码。

Markdown、Obsidian Vault、求职、学习、模型、手机和创作数据不参与此次迁移。

## 验证结果

覆盖四个来源固定顺序、来源编辑、金额口径、确认与作废状态、十二个月趋势、迁移快照、失败回滚、页面表单、旧 URL 404 和移动端隔离。

## 同步文档

- `docs/features/income.md`
- `docs/guides/income-workflow.md`
- `docs/architecture/README.md`
- `docs/architecture/storage.md`
- `docs/features/privacy-recovery.md`
- `docs/development/testing.md`
- `PROJECT_STATUS.md`
