---
date: 2026-08-25
status: completed
type: feature
areas:
  - publishing
  - privacy
  - storage
interfaces:
  - /settings/wechat
  - /publish/{id}/wechat/preflight
  - /publish/{id}/wechat/confirm
  - /publish/{id}/wechat/duplicate
data_migration: wechat_publishing v1
compatibility: preserved
rollback: revert this feature batch; keep the database migration record and delete Keychain credentials explicitly
verification:
  - tests/test_wechat.py
  - tests/test_publishing.py
  - full pytest and ruff
commit: pending
---

# 微信公众号草稿箱直推

## 背景与目标

在保留富文本复制和 HTML 下载的基础上，增加使用微信官方接口创建公众号草稿的明确确认流程，不把工作台扩展为自动发表系统。

## 最终行为

- 只有未归档文章可以进入草稿推送。
- AppID 和 AppSecret 保存到 macOS 钥匙串，连接测试和最终确认才联网。
- 同时支持可选的后端环境变量兼容配置，但不把真实密钥写入仓库或 LaunchAgent。
- 发布页复用当前最终导出正文，将公式转图并内嵌图片，再进入本地预检和二次确认。
- 正文图片、封面全部上传成功后才创建草稿；相同版本默认幂等。
- 创建草稿超时时记录结果未知，不自动重试或发表。
- 连接测试使用只读草稿数量接口验证权限；微信明确拒绝失效 Token 时只刷新并重试失败操作一次。

## 接口与数据

新增公众号设置、连接测试、推送预检、确认和明确副本接口。`workspace.db` 新增 `wechat_publishing` v1，只保存最小推送元数据；完整正文位于 24 小时私有临时任务中。

## 兼容与回滚

原文章、公众号排版、复制、下载和润色候选流程保持兼容。回滚代码不会修改文章；钥匙串凭证需在设置页或 macOS 钥匙串中明确删除。

## 验证结果

- 模拟微信接口验证 Token、正文图片、封面和草稿创建顺序。
- 验证外部图片、正文篡改、结果未知、幂等元数据和凭证命令行泄漏防护。

## 同步文档

- `docs/features/publishing-video.md`
- `docs/features/privacy-recovery.md`
- `docs/guides/creation-workflow.md`
- `docs/architecture/storage.md`
- `docs/operations/troubleshooting.md`
