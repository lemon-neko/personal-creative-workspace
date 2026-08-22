# 更新记录模板

复制本文件时保留下列 front matter 字段，并删除本说明段。`status` 只允许 `completed`，因为本目录不保存计划。

```yaml
---
date: YYYY-MM-DD
status: completed
type: feature
areas:
  - module-name
interfaces:
  - none
data_migration: none
compatibility: preserved
rollback: revert the feature batch commit
verification:
  - targeted tests
commit: pending
---
```

## 标题

## 背景与目标

说明为什么需要调整，以及完成标准。

## 最终行为

只记录已经落地的用户行为和系统边界。

## 接口与数据

记录页面、内部接口、数据格式和迁移变化；没有变化时明确写“无”。

## 兼容与回滚

说明旧内容、旧链接和已有数据如何处理，以及安全回滚方式。

## 验证结果

记录实际运行的测试、静态检查、安全检查和人工验收结果。

## 同步文档

列出本批次更新的权威功能、架构、指南或运行文档。
