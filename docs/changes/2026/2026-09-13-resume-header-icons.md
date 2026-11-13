---
date: 2026-09-13
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
  - tests/test_resume_studio.py
  - full pytest
  - ruff
  - JavaScript syntax check
  - security guards
commit: pending
---

# 简历页眉图标与分区线

## 背景与目标

国内版简历页眉原本只通过纯文字和点号组织联系方式，视觉识别速度不足。目标是在不改变简历数据和 ATS 输出的前提下，用小型线性图标与清晰分区提升招聘者的扫描效率。

## 最终行为

- 国内版页眉保持姓名居中，联系方式与职业信息分成两行。
- 电话、邮件、网站、GitHub、经验、目标岗位、教育、地点和年龄使用同一套 Tabler Icons 线框图标。
- 同行项目使用短竖线分隔；空字段不会留下图标或分隔线。
- 页眉底部使用浅灰横线和短羽白青起始段。
- 工作台初始预览、实时编辑预览、打印 HTML 和国内版 PDF 使用一致结构。
- ATS 版继续输出纯文本，不包含可见图标和装饰强调线。

## 接口与数据

页面和 PDF 接口保持不变；不增加字段、数据库迁移或私人资产。图标作为本地 Jinja2 模板内的 SVG 使用，运行时不访问网络。

## 兼容与回滚

旧简历无需整理即可显示新页眉。回滚模板、脚本和样式即可恢复原排版，不需要恢复数据库或私人文件。

## 验证结果

- 验证完整、部分和空联系方式不会产生空图标或连续分隔线。
- 验证长字段可换行且不与照片重叠。
- 验证国内版包含图标与分区线，ATS 版保持纯文本。
- 简历与文档定向测试 19 项通过，完整 Pytest 262 项通过。
- Ruff、JavaScript 语法、应用导入、安全守卫和 Git diff 检查通过。
- 在当前国内版实时预览中确认图标、照片避让与页眉横线正常显示。

## 同步文档

- `docs/features/career-learning.md`
- `docs/development/README.md`
- `docs/development/third-party-assets.md`
