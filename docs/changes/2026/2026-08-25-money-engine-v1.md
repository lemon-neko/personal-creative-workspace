---
date: 2026-08-25
status: completed
type: feature
areas:
  - income
  - assistant
  - workspace
interfaces:
  - /income/products/{id}
  - /income/products/{id}/metrics
  - /income/products/{id}/validation
  - /income/products/{id}/roles/{role_key}
data_migration: income v1 to v2 with pre-upgrade snapshot
compatibility: existing sources and ledger preserved
rollback: restore the pre-income-v2 database snapshot and revert this feature batch
verification:
  - 24 income tests passed
  - 223 non-browser tests passed
  - 3 browser tests passed
  - desktop and 390px income views passed without horizontal overflow
  - Ruff passed
  - application import passed
  - security guard passed
commit: pending
---

# Money Engine V1

## 背景与目标

收入面板继续保持极简，但需要回答“机器是否在没有私聊销售和人工交付的情况下赚到第一笔钱”。本批次只增加一个数字产品验证闭环，不恢复机会池、扫描器或后台 Agent。

## 最终行为

收入首页展示首个 ¥9.9 产品、最新漏斗快照、五张职责卡和严格通关状态。产品控制面维护 GitHub、公众号和面包多三个公开入口；作者手工记录漏斗与到账，第三方平台负责付款和文件交付。

只有陌生购买、无直接销售、第三方付款、自动交付、退款期结束、无退款，并且关联收入已确认、净到账至少 ¥1 时才通关。

## 接口与数据

新增单产品详情、漏斗、验证和职责表单。`income` 升级至 v2，增加唯一产品、漏斗快照、首单验证和固定职责卡表；升级前由统一数据库层创建快照。

## 兼容与回滚

四个固定来源、已有收支和统计口径保持不变。Money Engine 不连接第三方账号、不进入手机端和全局搜索。回滚时恢复升级前快照并回退功能批次。

## 验证结果

定向收入测试 24 项、非浏览器测试 223 项、浏览器验收 3 项全部通过；桌面与 390px 窄屏收入页均无横向溢出，Ruff、应用导入和 Git 私有数据守卫通过。

## 同步文档

- `docs/features/income.md`
- `docs/guides/income-workflow.md`
- `docs/architecture/storage.md`
- `PROJECT_STATUS.md`
