---
date: 2026-11-12
status: completed
type: feature
areas:
  - daily-work
  - localization
interfaces:
  - /
data_migration: none
compatibility: tasks and localization preferences preserved
rollback: refresh the previous Web bundle and restart
verification:
  - pinned Web build
  - Chromium language switch and persistence checks
commit: pending
---

## 日常工作语言切换

日常工作顶部可在简体中文与英文之间切换。语言在点击时保存到当前浏览器，切换时保留当前视图。两种语言都用 Inbox，任务菜单的交接动作也跟随所选语言。
