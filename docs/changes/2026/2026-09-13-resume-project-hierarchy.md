---
date: 2026-09-13
status: completed
type: refactor
areas:
  - career
  - resume
  - matching
  - pdf
  - frontend
interfaces:
  - GET /career/resumes/{id}/projects/structure
  - POST /career/resumes/{id}/projects/structure
data_migration: none
compatibility: preserved
rollback: revert this feature batch
verification:
  - tests/test_resume_studio.py
  - full pytest
  - ruff
  - javascript syntax check
  - security guards
commit: pending
---

# 简历教育顺序与项目三层结构

## 背景与目标

国内技术简历原先把教育经历放在项目之后，项目内容也只有一组扁平描述，招聘者难以快速区分项目背景、技术选择和作者贡献。本批次调整国内版阅读顺序，并为项目建立明确的信息层级。

## 最终行为

- 国内照片版固定按“职业摘要、教育经历、专业技能、工作经历、项目经历、自我评价”展示，ATS 版继续读取作者保存的区块顺序。
- 项目经历展示项目标题、项目简介、技术栈和个人职责；项目角色仍位于项目标题行。
- 编辑器分别提供项目简介、技术栈和个人职责字段。技术栈支持逗号或换行输入并在保存时去重。
- 旧版扁平项目可以进入独立映射预览。候选优先使用项目证据摘要和技术栈，只识别带明确技术标签的旧文本，其余内容保守归入个人职责。
- 映射预览不会写入数据。作者确认并通过 Revision 检查后才保存，过期页面返回冲突且不会覆盖新版本。
- 浏览器实时预览、打印 HTML、国内版 PDF 和 ATS PDF 使用相同语义结构；ATS 版只保留纯文本层级。

## 接口与数据

新增项目层级映射预览与确认表单。`structured_data` 中的项目增加 `summary`、`tech_stack` 和 `responsibilities`，继续保留旧 `description`。没有新增数据库表或迁移。

岗位匹配只索引当前生效的项目结构，避免重复计算旧描述；定制候选字段白名单同步支持项目简介、技术栈和个人职责。

## 兼容与回滚

未确认映射的旧简历继续按原有项目描述渲染。确认后旧描述仍保存在结构化 JSON 中，但不重复展示或索引。回滚代码即可恢复旧投影，不需要修改数据库或私人文档。

## 验证结果

- 验证国内版与 ATS 版区块顺序互不影响。
- 验证新旧项目数据、映射预览、确认写入、Revision 冲突及旧描述保留。
- 验证本地匹配、字段级定制、实时预览、打印 HTML 和 PDF 共享新结构。
- 完整验证结果以本批次最终命令输出为准。

## 同步文档

- `docs/features/career-learning.md`
- `docs/changes/README.md`
