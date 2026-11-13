---
date: 2026-11-13
status: completed
type: security
areas:
  - source-distribution
  - career
  - backup
  - daily
interfaces:
  - /
  - /career
data_migration: none
compatibility: existing private data remains readable
rollback: revert the release preparation commit
verification:
  - full Pytest with browser, pinned Autoloop and local Harness
  - fresh private data directory smoke test
  - Ruff, critical-module coverage and Git security guard
commit: pending
---

## 公开源码准备

## 背景与目标

让新安装从空投递表开始，为源码补齐许可声明，并维持桌面和移动访问边界。

## 最终行为

- 通用 Agent 工程路线随应用初始化。投递记录、简历和文档由使用者录入并保存在私有数据目录。
- 应用拒绝把私有数据根放进源码目录。Git 守卫拦截旧版内容路径和私有环境文件。
- 标准备份跳过符号链接。日常工作的 iframe 策略根据日常插件自身的验证状态设置。
- 工作台原创代码与文档采用 MIT 许可证，随源码分发的前端库附带上游许可证。移动图标保留原像素，去掉额外的 EXIF 元数据。

## 接口与数据

保留现有路由和数据库结构。首次启动不再生成内置职位，已经保存的职位和历史继续由现有查询读取。

## 兼容与回滚

现有安装继续使用仓库外的私有数据目录。回退本批次代码无需恢复数据库。

## 验证结果

- 完整 Pytest 通过。浏览器用例使用真实 Autoloop 与本机 Harness，模型响应由回环测试服务提供。
- 空数据目录下确认首页、AI 工作流、求职与学习返回 HTTP 200，职位、简历和文档为空。
- Ruff、关键模块覆盖率守卫、Git 安全守卫和源码敏感模式扫描通过。扫描命中均为测试样本或地址校验。

## 同步文档

- [求职与学习](../../features/career-learning.md)
- [隐私与恢复](../../features/privacy-recovery.md)
- [存储架构](../../architecture/storage.md)
- [运行维护](../../operations/README.md)
