---
date: 2026-08-22
status: completed
type: refactor
areas:
  - workspace-content
  - knowledge-obsidian
  - publishing-video
interfaces:
  - /ideas
  - /reviews
  - /articles
  - /publish
  - /knowledge
data_migration: none
compatibility: old detail URLs and historical source relations remain readable
rollback: revert the content-layering feature batch; private Markdown is unchanged
verification:
  - content type route tests
  - publishing source validation tests
  - knowledge source compatibility tests
commit: pending
---

# 内容分层与发布边界

## 背景与目标

原先随想、文章、回顾、知识沉淀和公众号入口容易混在同一创作流中。本批次把来源、正式知识和创作产物拆开，避免每条记录都被暗示需要拆卡或发布。

## 最终行为

- `/ideas` 只展示和维护随想，提供编辑、归档和整理为知识。
- `/reviews` 只展示中性周回顾，不默认进入知识库或公众号。
- `/articles` 独立创建和编辑文章，不要求关联随想或知识卡。
- `/publish` 只接受未归档文章；随想、回顾和知识卡不能执行发布操作。
- `/knowledge` 只维护“随想 → 原子知识卡 → 主题地图 → 学科地图”的正式结构。
- 微信公众号是文章导出方式，视频项目由文章派生。

## 接口与数据

新增文章列表、详情和回顾详情入口。底层 `ContentItem` 类型和状态保持不变，没有新增数据库表或迁移。新知识卡来源限定为未归档随想，并记录来源 Revision。

## 兼容与回滚

- 旧文章通过想法详情 URL 访问时跳转到文章页面。
- 历史知识卡中的文章来源继续可读取和追溯。
- 私人 Markdown 正文和现有关系不被自动重写。
- 回滚只需要还原该功能批次代码，不需要恢复数据。

## 验证结果

- 验证想法、回顾、文章、知识和发布列表只展示各自类型。
- 验证非文章不能预览、润色或保存公众号候选。
- 验证随想更新只标记知识卡待复核，不覆盖卡片正文。

## 同步文档

- [内容模型](../../architecture/content-model.md)
- [工作台与内容](../../features/workspace-content.md)
- [知识库与 Obsidian](../../features/knowledge-obsidian.md)
- [公众号与视频](../../features/publishing-video.md)
- [知识沉淀指南](../../guides/knowledge-workflow.md)
- [创作发布指南](../../guides/creation-workflow.md)
