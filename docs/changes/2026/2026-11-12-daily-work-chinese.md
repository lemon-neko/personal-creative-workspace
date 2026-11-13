---
date: 2026-11-12
status: completed
type: fix
areas:
  - daily-work
  - localization
interfaces:
  - /
data_migration: none
compatibility: installed tasks and plugin state preserved
rollback: refresh the previous Web bundle and restart
verification:
  - pinned Web build and Simplified Chinese translation coverage
  - existing Chromium profile and narrow-screen browser check
  - Web package refresh rollback test
commit: pending
---

## 日常工作简体中文

工作台内嵌的 Super Productivity 固定使用简体中文，补齐 511 项上游缺译，包括日历、任务菜单、设置和提示。日期格式仍可按偏好设置。更新只替换 Web 资源和校验值，保留浏览器里的待办和计时记录。
