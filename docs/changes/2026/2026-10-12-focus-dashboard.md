---
date: 2026-10-12
status: completed
type: feature
areas:
  - focus
  - workspace
  - career
  - assistant
interfaces:
  - /focus
  - /focus/checkin
  - /career/jobs/{id}/plan
data_migration: focus v1-v2 and career v7 in workspace.db
compatibility: existing URLs and records preserved
rollback: revert feature code and restore the pre-migration private database snapshot if required
verification:
  - targeted and full Pytest
  - Ruff and security guards
  - desktop and narrow viewport browser checks
commit: pending
---

# 阶段行动与首页看板

## 背景与目标

首页需要优先回答“当前主线、本周交付、今日行动和下一判断节点”，同时保留随想记录入口。

## 最终行为

作者可在本地维护阶段目标、交付物、行动、决策节点和周复盘；首页显示精简概况。职位增加手工跟进字段，学习、创作和周回顾页面明确区分阶段行动与原有专业流程。

## 接口与数据

新增 `/focus`、详情、历史和周复盘表单路由。`focus` v1–v2 与 `career` v7 进入统一 SQLite 迁移序列；v2 让决策节点保留手工状态，逾期节点在确认前持续可见。阶段真实数据仅写入仓库外私有库，代码和文档不包含私人正文。助手只接收事业主线白名单摘要。

## 兼容与回滚

原有页面和状态语义保留；旧职位自动获得默认 B 档及空白跟进字段。升级前自动保存数据库快照，迁移失败事务回滚。

## 验证结果

完整命令与最终结果见本次交付说明；测试只使用临时目录和虚构内容。

## 同步文档

更新阶段行动、工作台、求职学习、助手、创作、存储架构、操作指南与项目状态。
