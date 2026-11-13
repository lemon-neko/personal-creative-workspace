---
date: 2026-11-11
status: completed
type: refactor
areas:
  - workbench
  - navigation
  - frontend
interfaces:
  - desktop visual system and homepage search entry
data_migration: none
compatibility: existing routes and task data preserved
rollback: revert this batch
verification:
  - Chromium desktop and narrow viewport
  - full Pytest and security guard
commit: pending
---

## 工作台视觉更新

### 背景与目标

参考 AI Hot 的暖白背景、细边框、胶囊筛选和信息列表，统一工作台桌面版的视觉细节。[AI Hot](https://aihot.news/)

### 最终行为

导航按工作、内容和更多工具分组。今日页上方显示视图切换与全局检索。有待确认事项时，在任务列表上方集中显示。白色任务面板按逾期、未完成、已完成分组。

### 接口与数据

全局检索入口复用现有对话框与搜索地址。样式、模板和静态脚本更新不涉及数据库迁移。

### 兼容与回滚

今日与待安排继续使用现有地址和表单。可直接回退本批次文件。

### 验证结果

以虚构数据检查今日、待安排、键盘焦点、搜索入口及 320px 窄屏布局。完整 Pytest 293 项通过，Ruff、应用导入与安全守卫通过。

### 同步文档

- [开发说明](../../development/README.md)
- [工作台内容](../../features/workspace-content.md)
