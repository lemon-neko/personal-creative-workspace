---
date: 2026-11-12
status: completed
type: refactor
areas:
  - mobile
  - daily-work
interfaces:
  - GET / on mobile
  - GET /capture on mobile
  - POST /workflow/daily-snapshot on desktop
data_migration: IndexedDB drops only the obsolete knowledge metadata store
compatibility: Existing pairings, offline notes, pending edits, and conflict drafts are retained
rollback: Revert the batch, rebuild the Web bridge, and restart the installed services
verification:
  - isolated paired browser and real Super Productivity Web bridge
  - Pytest, Ruff, application imports, and security guard
commit: pending
---

## 移动工作台保留日常工作和随手记

## 背景与目标

手机用于快速查看工作进度和随手记录。知识整理继续在桌面或 Obsidian 进行。

## 最终行为

手机配对后默认进入只读日常看板，可以切换到随手记。「我的随想」保留离线编辑、待同步队列和人工冲突合并。手机知识库和拆卡入口下线。

## 接口与数据

桌面日常页通过可信 iframe 获取 Super Productivity 的当日任务标题和时间，经同源 CSRF 接口原子更新私有 `working/mobile-daily.json`。移动首页只向配对设备显示当天快照。看板不进入离线缓存，数据库无新迁移。

## 兼容与回滚

Service Worker 激活时清除旧移动知识缓存。IndexedDB 升级时仅删除旧知识元数据仓，配对和记录保持可用。回退时需要将桌面代码和已安装的 Web 桥接一起回退。旧知识离线副本可从已恢复的旧服务重新获取。

## 验证结果

使用虚构任务走通真实 Super Productivity Web 构建到已配对移动浏览器。窄屏浏览器验证两个入口、键盘访问、旧知识缓存清除、离线记录与冲突合并。完整 Pytest 304 项通过，Ruff、应用导入和安全守卫通过。Mac 已重启桌面与手机服务，现有 Tailnet HTTPS 入口经 IPv4 返回 200。Android 实机待验证。

## 同步文档

- [Android PWA](../../features/mobile-pwa.md)
- [手机安装与 Tailnet](../../operations/mobile-tailscale.md)
- [系统架构](../../architecture/README.md)
