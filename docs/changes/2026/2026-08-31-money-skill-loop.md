---
date: 2026-08-31
status: completed
type: refactor
areas:
  - income
  - assistant
  - privacy
interfaces:
  - GET /income/profile
  - POST /income/profile
  - GET /income/opportunities
  - POST /income/opportunities
  - GET /income/opportunities/{id}
  - POST /income/opportunities/{id}/evidence
  - POST /income/opportunities/{id}/verification
  - POST /income/opportunities/{id}/plan
  - POST /income/opportunities/{id}/retro
data_migration: income v3
compatibility: preserved
rollback: restore the pre-migration workspace.db snapshot and revert this batch
verification:
  - tests/test_income.py
  - full pytest
  - ruff
  - documentation tests
  - security guards
commit: pending
---

# 赚钱验证闭环

## 背景与目标

原收入页能记账并跟踪首个数字产品，但“为什么值得做”仍缺少严格依据。本批次参考 `XBuilderLAB/cheat-on-money` 的公开方法，把赚钱判断收敛为画像、真实需求证据、反诈核验、最小试验和预测/实际复盘，同时保持工作台本地、手工和可回滚。

## 最终行为

- 收入首页继续以真实到账和四个固定收入来源为核心，同时显示当前画像、候选和验证阻断。
- 候选必须说清付费客户和资金流，不把赚钱教程当需求证据。
- “可验证”要求两个不同来源的两年内证据，且至少一个在一年内，并记录交叉印证。
- A1–A6 硬性红旗会自动标记高风险并停止；B1–B6 作为可疑信号保留。
- 只有核验通过后才能冻结执行预测；预测不可回改，实际结果单独复盘。
- 实际到账仍只取自已确认收入账本，复盘金额不参与统计。
- 应用不自动扫描、不访问证据链接、不登录第三方平台、不调用模型。

## 接口与数据

`income` 子系统从 v2 升至 v3，迁移前由统一迁移器创建数据库快照。新增 `money_profiles`、`money_opportunities`、`money_evidence` 和 `money_retros`。现有 `income_sources`、`income_entries`、Money Engine 产品、漏斗、职责和首单验证表保持不变。

助手只新增脱敏画像层级、当前候选、证据计数、验证状态和下一步，不包含证据全文、账本备注和复盘正文。

## 兼容与回滚

现有四个收入来源、所有收支记录、产品状态、漏斗快照和第一笔 ¥1 验证原样保留。首个产品被关联为“待核验”候选，不伪造市场证据或可行结论。回滚时先停止旧进程，恢复迁移前 `workspace.db` 快照，再回退代码。

## 验证结果

- 定向收入测试覆盖迁移、画像、证据时效、独立来源、硬红旗、预测冻结、复盘和页面表单。
- 完整测试、Ruff、文档检查、应用导入和 Git 安全守卫通过后交付。

## 同步文档

- `docs/features/income.md`
- `docs/guides/income-workflow.md`
- `docs/architecture/storage.md`
- `docs/features/privacy-recovery.md`
- `PROJECT_STATUS.md`
