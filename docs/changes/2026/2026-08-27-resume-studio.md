---
date: 2026-08-27
status: completed
type: feature
areas:
  - career
  - resume
  - model-gateway
  - pdf
interfaces:
  - /career/resumes
  - /career/resumes/{id}
  - /career/resumes/{id}/match/{job_id}
  - /career/resumes/{id}/pdf
data_migration: career v4 foundation; photo import extends the subsystem in a separate v5 batch
compatibility: legacy resume records preserved without content rewrite
rollback: restore the pre-career-v4 database snapshot and revert this feature batch
verification:
  - tests/test_resume_studio.py
  - tests/test_model_gateway.py
  - full pytest and ruff
commit: pending
---

# 简历工作室与岗位定制

## 背景与目标

原简历页只登记文件和版本，无法形成“主简历 → 选择职位 → 检查差距 → 确认修改 → 导出”的闭环。本批次参考 Resume Matcher 的核心工作流，并按羽白工作台既有本地安全架构原生实现。

## 最终行为

- 已有简历继续作为 `legacy` 历史记录查看、下载和归档，不会自动转换或改写。
- 作者明确选择已上传文件，经本地规则或模型候选预览、人工校对后创建唯一主简历。
- 结构化编辑页支持字段编辑、项目证据选择、区块顺序/可见性和 A4 单栏实时预览。
- 选择现有职位后，本地生成关键词覆盖与结构完整度报告；空关键词不会伪造百分比。
- 手工复制或逐项确认模型差异后创建 `tailored` 子版本，永不覆盖主简历、候选人档案或项目证据。
- PDF 通过本机 Playwright 从内存 HTML 按需生成；无 Chromium 时提供清晰诊断和打印 HTML 回退。

## 接口与数据

Career 子系统升级为 v4，`resumes` 增加类型、父版本、职位、结构化内容、事实源指纹、Revision、模板和主版本标记。迁移前自动保存数据库快照，并用唯一索引保证只能存在一份当前主简历。

`ModelGateway` 新增 `resume-parse` 与 `resume-tailor`，输入/输出上限为 24K/6K。模型任务仍遵循完整外发预览、Provider 限制、来源校验和人工确认。私有照片和双版本导出见后续的[现有简历与照片导入](2026-08-27-resume-photo-import.md)批次。

## 兼容与回滚

旧简历文件、版本、项目关系和状态保持原样。回滚时先停止工作台，恢复 `working/db-migrations/` 中 career v3 到 v4 前的 SQLite 快照，再回退本批次代码；私人上传文件不需要迁移。

实现没有引入 Resume Matcher 的 Next.js 前端、第二套数据库或职位追踪器。设计参考项目采用 Apache-2.0；当前实现为工作台原生代码。

## 验证结果

- 覆盖 v3 到 v4 升级、快照、重复初始化和旧记录保留。
- 覆盖主/子版本、Revision 冲突、事实源变化、本地匹配、人工候选校验和虚构项目拒绝。
- 覆盖工作室导入、详情、职位匹配和打印 HTML 下载。
- 完整 Pytest：248 项通过（包含 3 项 Playwright 浏览器验收）。
- Ruff、JavaScript 语法、应用工厂无副作用导入、文档检查和 Git 私有数据守卫通过。
- 使用虚构简历在本机系统 Chrome 完成内存 PDF 实际生成，文件头与内容长度有效。

## 同步文档

- [求职与学习](../../features/career-learning.md)
- [模型与成本](../../features/model-cost.md)
- [求职学习指南](../../guides/career-workflow.md)
- [存储架构](../../architecture/storage.md)
- [项目状态](../../../PROJECT_STATUS.md)
