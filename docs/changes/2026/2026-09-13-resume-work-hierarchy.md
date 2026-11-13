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
  - security guards
commit: pending
---

# 工作经历二层分区

## 背景与目标

原简历模板把每条工作记录都渲染为独立公司，无法清楚表达作者在同一家公司先后承担的多个岗位。目标是在不扩展数据库、不改写正文的前提下，让招聘者先识别公司，再扫描各岗位及成果。

## 最终行为

- 工作经历使用“公司 → 岗位 → 成果”的二层结构。
- 公司层展示公司名、地点和汇总任职时间。
- 岗位层展示岗位名称、该岗位时间和原成果列表。
- 岗位成果中符合“方向 - 项目（技术）”格式的短行提升为职责小标题，后续成果缩进显示。
- 相同公司名的记录按首次出现位置归组，岗位保持原有顺序。
- 编辑区提示作者通过相同公司名新增岗位，实时预览同步展示归组结果。
- 国内技术版使用主题色层级线；ATS 版保留相同语义结构但移除装饰线。

## 接口与数据

页面和 PDF 接口保持不变。新增只读工作经历投影，继续使用现有 `work_experience` 数组，不增加字段或数据迁移。

## 兼容与回滚

单岗位公司同样按二层结构显示；旧简历无需整理即可加载。回滚投影、模板、脚本和样式即可恢复原排版，不需要恢复数据库。

## 验证结果

- 验证同公司岗位归组、公司顺序、岗位顺序和任职时间汇总。
- 验证归组不会修改结构化简历原始数据。
- 验证实时预览、打印 HTML、国内版 PDF 和 ATS 版共享相同语义层级。
- 完整验证结果以本批次最终命令输出为准。

## 同步文档

- `docs/features/career-learning.md`
- `docs/guides/career-workflow.md`
