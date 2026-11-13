---
date: 2026-11-13
status: completed
type: refactor
areas:
  - plugin-runtime
interfaces:
  - POST /settings/runtime/plugins/{plugin_id}/{action}
data_migration: none
compatibility: preserved
rollback: revert the Task 05 changes
verification:
  - runtime fault injection
  - browser verification with pinned upstream packages
  - full Pytest, Ruff, import, architecture audit and security guards
commit: pending
---

## Task 05 · 插件注册与进程监督

## 背景与目标

旧插件启动器以固定间隔重试，丢弃子进程输出。静态注册同时装配 Router。现在各职责有独立入口，用户可判断哪个服务失败并执行恢复。

## 最终行为

设置页区分 Super Productivity、Autoloop Hub 和 Worker。自动恢复有限次，人工停止取消退避并收尾。插件日志只保留有界安全诊断。

## 接口与数据

原有 245 条桌面路由的路径、名称、方法与相对顺序保留。新增一个插件操作 POST 路由，移动路由仍为 17 条。包版本、原有端口、数据位置、规则和协议不变。日志存放在私有 `working/plugins/logs/`。没有 SQLite 迁移。

## 兼容与回滚

回退 Task 05 的代码即可恢复原启动路径。私有业务数据、Autoloop 规则和凭据仍可读取。

## 验证结果

完整 Pytest 384 项通过。Chromium 使用固定 Web 构建和真实 Autoloop，验证三个独立 Ready 状态、重启表单和 IndexedDB 保留。真实 Hub 重启后已验收轮次保留，模型调用次数未增加。故障注入覆盖损坏包、启动超时、健康失败、Worker 崩溃、预算耗尽、锁竞争、进程组回收和日志脱敏。Ruff、桌面及移动 ASGI 导入、Git 安全守卫和 SQLite 表与迁移版本回归通过。架构审计扫描 138 个模块、398 条导入边，只剩内容与知识库间的 4 条循环边。

## 同步文档

[插件运行时架构](../../architecture/plugin-runtime.md) · [插件操作指南](../../operations/workbench-plugins.md)
