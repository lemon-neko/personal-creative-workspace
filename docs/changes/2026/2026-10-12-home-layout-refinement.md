---
date: 2026-10-12
status: completed
type: refactor
areas:
  - workspace
  - focus
  - frontend
interfaces:
  - /
  - /?view=...
  - /?q=...
  - /partials/workspace-feed
data_migration: none
compatibility: existing filtered URLs and quick capture behavior preserved
rollback: revert this template, home style and route context batch
verification:
  - targeted and full Pytest
  - Ruff, app import and security guards
  - desktop, tablet, 390px and 320px browser checks
commit: pending
---

# 首页精简排版

## 背景与目标

阶段行动上线后，首页需要缩短阅读路径，使今日行动、双主线、本周交付和决策节点在首屏形成稳定层级。

## 最终行为

默认首页用两行看板展示四项行动信息；窄屏依次排列。目标行和今日行动可进入目标详情。阶段名称与结束日期缩为辅助信息；其他阶段行动只留中性入口。下半部保留快速记录及想法库、创作、助手、周回顾入口，完整随想创作流通过想法库查看。

## 接口与数据

默认 `/` 渲染精简版；带 `view` 或 `q` 参数的旧首页地址继续渲染原有随想筛选结果。`/partials/workspace-feed` 保持可用。首页上下文移除了无需展示的跨模块统计读取。数据模型、私有计划和 Android PWA 数据范围没有变化。

## 兼容与回滚

快速记录继续使用原表单路由、CSRF、可选字段和保存后反馈；旧筛选链接与内容状态语义保留。回滚只需恢复本批次的模板、样式和首页上下文，不需要迁移私有数据。

## 验证结果

相关与完整 Pytest、Ruff、应用导入、安全守卫及桌面、平板和窄屏浏览器检查通过。浏览器检查覆盖信息顺序、横向溢出、键盘焦点、链接可达性和首页私人详情隔离。

## 同步文档

更新工作台与内容、阶段行动功能文档及 README 入口摘要。
