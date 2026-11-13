---
date: 2026-11-13
status: completed
type: docs
areas:
  - architecture
  - tests
interfaces:
  - architecture audit CLI
  - architecture Pytest suite
data_migration: none
compatibility: desktop and mobile runtime contracts preserved
rollback: revert documentation, the audit tool and architecture tests
verification:
  - isolated baseline and full Pytest with browser and plugin fixtures
  - Ruff and Git security guard
  - desktop and mobile imports and startup
  - before and after route, schema and migration comparison
commit: pending
---

## Task 01 架构基线

## 背景与目标

为应用装配、进程管理、检索和业务模块的渐进重构建立可复现的源码及存储基线。

## 最终行为

开发者可以生成内部依赖和循环清单。Pytest 阻止新增循环边和逆向入口依赖，检查 Router SQL 边界、工厂导入隔离、数据库表归属和迁移版本。

## 接口与数据

新增 `tools/architecture_audit.py`，支持文字和 JSON 输出。架构测试使用临时数据目录。业务路由、数据库表与迁移版本保持兼容。

## 兼容与回滚

本批次改动限于文档、静态分析和测试。回退这些文件不需要恢复数据库。

## 验证结果

- 全量 Pytest 包含 Playwright、真实 Autoloop 和本机 Harness，模型响应由回环 fixture 提供。
- Ruff、应用工厂及 ASGI 导入、隔离启动、架构边界与安全守卫通过。
- 对照 245 个桌面和 17 个移动路由/挂载项，以及临时目录内 SQLite schema 和迁移版本，均与起点一致。

## 同步文档

- [架构审计报告](../../architecture/audit-report.md)
- [系统架构](../../architecture/README.md)
- [开发说明](../../development/README.md)
