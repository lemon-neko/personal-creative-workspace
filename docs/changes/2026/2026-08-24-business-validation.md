---
date: 2026-08-24
status: completed
type: feature
areas:
  - business-income
  - assistant
  - search
interfaces:
  - /income
  - /income/signals
  - /income/opportunities
  - /income/experiments
  - /income/ledger
  - /income/settings
data_migration: workspace.db bounty_income v2 with pre-upgrade snapshot
compatibility: existing bounty records and payouts remain authoritative and are projected without duplication
rollback: revert this feature batch and restore the pre-v2 database snapshot if a full data rollback is required
verification:
  - tests/test_bounty_income.py
  - full pytest and ruff
  - application import, docs and security guard
commit: pending
---

# 商业与收入验证系统

## 背景与目标

原悬赏模块依赖已降级的 Gitee 公开广场，并把收入来源限制在接外部任务。本批次将其升级为通用商业验证控制面，聚焦零成本 AI 工具和一次性数字产品。

## 最终行为

新增需求信号、八维机会评分、合规阻断、双 Offer 产品实验、七日指标快照和统一现金账本。商业验证必须关联真实到账；访问、注册、询价和支付尝试只作为过程信号。

GitHub 与 RSS 发现按来源隔离，只保存公开摘要。页面加载不联网，外部内容不能自动创建实验。发布、收款、交付和外部写入仍由作者确认。

## 兼容、迁移与回滚

`bounty_income` 从 v1 升级到 v2，迁移前自动建立数据库快照。原悬赏、事件和到账表不改写；统一总览通过查询投影旧到账，避免重复记账。Android PWA 没有新增商业或财务接口。

## 验证结果

覆盖迁移幂等、评分公式、阻断项、实验成功门槛、人民币分与费用计算、公开来源隔离、RSS 私网拒绝、页面烟雾测试和旧悬赏兼容。

## 同步文档

- `docs/features/business-income.md`
- `docs/guides/business-workflow.md`
- `docs/architecture/README.md`
- `docs/architecture/storage.md`
- `docs/features/privacy-recovery.md`
- `docs/development/testing.md`
- `PROJECT_STATUS.md`
