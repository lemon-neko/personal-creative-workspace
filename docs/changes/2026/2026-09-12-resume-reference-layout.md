---
date: 2026-09-12
status: completed
type: refactor
areas:
  - career
  - resume
  - pdf
  - frontend
interfaces:
  - GET /career/resumes/{id}
  - GET /career/resumes/{id}/pdf
data_migration: none
compatibility: preserved
rollback: revert this feature batch
verification:
  - resume studio tests
  - PDF visual review
  - full pytest
  - ruff
  - security guards
commit: pending
---

# 国内技术简历参考排版校准

## 背景

技术社招版原先已经具备照片、单栏 A4 和结构化编辑能力，但页眉与经历层级仍偏向通用工作台样式，不够接近国内招聘者熟悉的快速扫描格式。

## 最终行为

- 国内技术版使用居中的姓名与两行紧凑身份信息，照片固定在页眉右侧。
- 章节标题改为小面积主题色斜切标签，正文保持白底和高信息密度。
- 工作、项目和教育经历统一使用“组织或项目 / 角色或专业 / 时间”三列标题行。
- 职业摘要、技能和项目正文继续来自原结构化数据，不因排版调整而改写。
- 无照片 ATS 版仍保持纯文本、机器读取友好的单栏输出。

## 页面与数据

本批次只修改简历实时预览和打印模板，没有新增页面、接口、数据库字段或数据迁移。现有 `china_single_photo` 与 `ats_single` 模板键保持不变。

## 兼容、迁移与回滚

已有简历、照片、Revision、岗位匹配和导出链接全部兼容。回滚模板、CSS 与实时预览脚本即可恢复原视觉，不需要恢复数据库。

## 验证

- 结构化简历测试覆盖国内版双行页眉、三列经历和斜切章节标题。
- 使用虚构数据渲染 A4 PDF，并逐页检查页眉、章节、照片和分页。
- 运行完整 Pytest、Ruff、应用导入和安全守卫。

## 更新的权威文档

- [求职与学习](../../features/career-learning.md)
- [求职工作流](../../guides/career-workflow.md)
