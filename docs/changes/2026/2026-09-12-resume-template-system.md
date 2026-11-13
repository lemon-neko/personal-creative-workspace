---
date: 2026-09-12
status: completed
type: refactor
areas:
  - career
  - resume
  - frontend
  - pdf
interfaces:
  - POST /career/resumes/{id}
  - GET /career/resumes/{id}/pdf
data_migration: none
compatibility: preserved
rollback: revert this feature batch
verification:
  - tests/test_resume_studio.py
  - full pytest
  - ruff
  - security guards
commit: pending
---

# 简历模板系统优化

## 背景与目标

原简历工作室只有一套通用单栏表现，编辑区层级偏重，技术能力、履历和项目证据不便快速扫描。本批次参考小林简历模板库中的技术社招信息结构，将现有数据改造成受控双模板系统。

## 最终行为

- 简历详情可以选择“技术社招版”或“ATS 基础版”。
- 技术社招版固定优先展示摘要、专业技能、工作经历和项目经历，适合 AI Agent 应用开发社招场景。
- ATS 基础版保留作者设置的区块顺序；无照片 ATS 导出始终使用该模板。
- 编辑器实时预览、国内版 PDF、ATS PDF 和打印 HTML 复用同一语义模板。
- 照片设置改为低干扰折叠区，编辑页收敛为标题、导出、内容和实时预览四个层级。

## 接口与数据

`POST /career/resumes/{id}` 增加受控 `template_key` 保存。没有新增数据库字段或迁移，继续复用现有 `resumes.template_key`。模板只影响展示顺序和排版，不改变结构化简历正文。

## 兼容与回滚

已有 `china_single_photo` 与 `ats_single` 值继续有效。原简历、私有照片、Revision、事实源指纹和导出 URL 均保持兼容。回滚代码即可恢复旧视觉，不需要恢复数据库。

## 验证结果

- 验证技术社招版与 ATS 版的确定性区块顺序。
- 验证模板选择持久化、无效值拒绝和 Revision 保存。
- 验证国内版与 ATS 版打印 HTML 使用对应模板且 ATS 版不依赖照片。
- 完整验证结果以本批次最终命令输出为准。

## 同步文档

- `docs/features/career-learning.md`
- `docs/guides/career-workflow.md`
- `docs/architecture/storage.md`
