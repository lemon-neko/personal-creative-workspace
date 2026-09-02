---
date: 2026-08-24
status: completed
type: feature
areas:
  - bounty-income
  - assistant
  - search
interfaces:
  - /income
  - /income/bounties/{id}
data_migration: workspace.db bounty_income v1 with pre-upgrade snapshot
compatibility: preserved; no existing private content is changed
rollback: revert the feature batch and restore the pre-migration database snapshot if required
verification:
  - tests/test_bounty_income.py
  - full pytest and ruff
  - application import and security guard
commit: pending
---

# 悬赏收入一期

## 背景与目标

工作台需要区分公开机会、执行进度和真正进入作者账户的收入，避免把标称赏金或平台余额当作“已赚到”。

## 最终行为

新增本地悬赏收入驾驶舱、详情时间线、每日 Gitee 公开只读扫描、Codex 公开执行任务包和人民币到账账本。首页从 `¥0.00` 开始，只有经过验收、平台结算和二次确认的实际提现才进入已赚合计。

扫描不调用模型，不保存 Gitee 登录或支付资料。认领和 PR 发布继续由作者分别确认并在外部平台手工完成。手机端不提供收入数据。

## 接口与数据

新增 `/income`、`/income/bounties/{id}` 及其扫描、设置、批准、进度、PR、结算和提现表单。`workspace.db` 新增 `bounty_income` v1 迁移，金额以人民币分保存，迁移前由统一数据库层建立快照。

首页、全局搜索和个人助手接入脱敏的收入与活跃悬赏摘要；助手上下文不包含支付资料。

## 兼容与回滚

没有移动或改写现有 Markdown、知识库、求职数据和设备会话。回滚代码不会删除新增表；如需完全回退，可在应用停止后使用迁移前数据库快照。

## 验证结果

覆盖金额精度、状态跳级拒绝、迁移幂等、扫描解析与失败保留、每日自动扫描标记、页面不联网、收入路由和手机隔离。完整验证结果在本批次完成时记录。

## 同步文档

- `docs/features/bounty-income.md`
- `docs/guides/bounty-workflow.md`
- `docs/architecture/README.md`
- `docs/architecture/storage.md`
- `docs/development/testing.md`
- `PROJECT_STATUS.md`
