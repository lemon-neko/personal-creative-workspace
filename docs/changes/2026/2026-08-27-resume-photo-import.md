---
date: 2026-08-27
status: completed
type: feature
areas:
  - career
  - resume
  - private-assets
  - pdf
interfaces:
  - /career/resumes
  - /career/resumes/{id}
  - /career/resumes/{id}/photo
  - /career/resumes/{id}/pdf
data_migration: career v5 with pre-upgrade and pre-import snapshots
compatibility: original document and legacy resume records preserved; older structured resumes load without photo fields
rollback: restore the pre-import workspace database snapshot and remove only the unreferenced private resume asset
verification:
  - tests/test_resume_studio.py
  - full pytest and ruff
commit: pending
---

# 现有简历与照片导入

## 背景与目标

简历工作室已经支持结构化主简历，但作者已有的权威 DOCX 尚未真正进入该流程，证件照也没有安全的私有资产边界。本批次增加确定性 DOCX 解析、照片筛选、幂等导入和双版本导出，整个过程不调用模型或外部服务。

## 最终行为

- 通过 SHA-256 复用已经保存的私有 DOCX，不产生重复上传文件。
- 本地解析正文、文本框、项目符号和内嵌图片；跳过重复装饰文本，并把待确认结果展示在导入预览页。
- 主简历创建前保存 SQLite 快照。相同文档重复执行时返回已有主简历，不产生第二份记录。
- 证件照按真实签名、尺寸、长宽比和哈希筛选；重复图片只保存一次，小图标和装饰图片不会成为简历照片。
- 原始 DOCX、已有 `legacy` 记录和项目证据保持不变。项目文字保存在简历版本内，只通过既有项目 ID 建立引用。
- 简历详情可更换或移除照片，并提供带照片的国内版和无照片的 ATS 版 PDF/HTML。

## 数据与隐私

Career 子系统升级为 v5：新增 `resume_assets`，并在 `resumes` 增加可空的 `photo_asset_id`。照片采用随机文件名存入仓库外 `documents/resume-assets/`，目录权限为 `0700`、文件权限为 `0600`。

照片不进入静态资源、全局搜索、模型任务、移动端快照或日志。PDF 在内存中嵌入照片，下载响应禁止缓存且不默认持久化。

## 兼容与回滚

旧结构化简历没有照片字段时继续加载；定制简历默认继承主简历照片引用。导入失败时清理本次新建且未被引用的照片资产。回滚时恢复导入前数据库快照，再删除确认未被任何简历引用的对应私有照片；原始 DOCX不需要恢复。

## 验证结果

- 覆盖 DOCX 文本、教育、工作经历、项目、重复段落、自我评价和照片识别。
- 覆盖相同文档幂等导入、数据库快照、旧记录保留、照片权限与受保护读取。
- 覆盖国内版包含照片、ATS 版不含照片且文字结构一致。

## 同步文档

- [求职与学习](../../features/career-learning.md)
- [求职学习指南](../../guides/career-workflow.md)
- [存储架构](../../architecture/storage.md)
- [项目状态](../../../PROJECT_STATUS.md)
