---
date: 2026-11-13
status: completed
type: refactor
areas:
  - career
  - architecture
interfaces:
  - app.career.CareerRepository
  - Career application services
data_migration: none
compatibility: existing routes, persisted schemas and public imports preserved
rollback: revert the Career package refactor
verification:
  - existing and new Career tests
  - full Pytest and Playwright
  - Ruff and Git security guard
  - route and migration comparison
commit: pending
---

## Task 03 Career 领域拆分

## 背景与目标

将档案、简历、投递和学习从同一个仓储文件拆分为独立模型、用例与持久化职责。

## 最终行为

四个服务经共享 SQLite Unit of Work 组织跨域操作。简历创建校验关联证据，投递快照保存指定版本。技能确认整批提交，导入主简历失败时同时回滚照片登记并清理本次产生的文件。

## 接口与数据

旧 CareerRepository、类型导入和 API 延续。既有 SQLite 迁移序列保持第 8 版。

## 兼容与回滚

保留现有应用入口、私有文件路径和数据格式。可直接回退代码提交。

## 验证结果

测试覆盖同连接、异常回滚、历史迁移、浏览器自动保存和已投递简历快照。

## 同步文档

- [Career 领域架构](../../architecture/career-domain.md)
- [开发说明](../../development/README.md)
