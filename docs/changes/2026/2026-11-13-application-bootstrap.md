---
date: 2026-11-13
status: completed
type: refactor
areas:
  - desktop-bootstrap
  - application-lifecycle
interfaces:
  - app.main.create_app
  - app.bootstrap.dependencies.get_container
data_migration: none
compatibility: existing desktop and mobile contracts preserved
rollback: revert the desktop bootstrap batch without changing private data
verification:
  - baseline and full Pytest with browser, Autoloop and local Harness
  - Ruff, critical-module coverage and Git security guard
  - ASGI imports, startup and route/schema comparison
commit: pending
---

## Task 02 桌面启动装配

## 背景与目标

明确桌面应用的配置、依赖构造、HTTP 装配和资源生命周期，为后续进程监督和业务切片保留可测试的入口。

## 最终行为

- 桌面工厂构造独立 AppContainer。新处理器可通过 FastAPI Depends 获取容器，旧 state 属性读写同一实例。
- Lifespan 管理搜索首次同步、周回顾和插件上下文。部分启动失败会等待后台任务及插件资源收尾，启动索引的 SQLite 错误可降级。
- 私有附件路径使用容器注入，保留原来的路由和访问校验。

## 接口与数据

旧工厂参数、ASGI 入口、插件导航和桌面、移动安全边界延续。数据库结构、迁移版本和私有数据目录未变。

## 兼容与回滚

回退本批次只需恢复桌面装配代码。独立移动网关和工作流协议继续使用原实现。

## 验证结果

- 容器依赖、旧属性替换、临时备份恢复、启动及取消异常路径有独立测试。
- 隔离启动对照 245 个桌面和 17 个移动路由/挂载项、两份 SQLite schema 及迁移版本。
- 使用临时目录和虚构模型响应执行完整回归。

## 同步文档

- [应用启动与依赖装配](../../architecture/application-bootstrap.md)
- [系统架构](../../architecture/README.md)
- [重构路线图](../../architecture/refactoring-roadmap.md)
