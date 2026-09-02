---
date: 2026-08-28
status: completed
type: refactor
areas:
  - career-learning
  - assistant
  - search
interfaces:
  - POST /learning/stages/{stage_id}
data_migration: career v6
compatibility: preserved
rollback: restore the automatic pre-migration workspace database snapshot and revert this feature batch
verification:
  - targeted career, assistant and application tests
  - full pytest and ruff
  - application import and security guard
commit: pending
---

# Agent 应用开发学习路线重构

## 背景与目标

旧学习页同时展开岗位、指标、六张能力卡和四周研读表单，学习顺序不够清晰。此次把岗位要求保留为路线依据，把默认页面收敛为唯一工程框架和四个按依赖推进的阶段。

## 最终行为

- `/learning` 顶部只显示当前阶段、下一步行动和总进度。
- 工程框架按软件工程基础、Model、Context、Runtime、Action、Orchestration、Production & Quality、Application 展示。
- 四个阶段依次为手写最小 Agent、拆 OpenHands、学 LangGraph、看框架与产品化。
- 当前阶段默认展开，其余阶段折叠；每阶段独立保存状态、Commit SHA、测试结果和私人复盘。
- 岗位快照、能力差距、旧路线、战役和维护表单进入次级折叠区域。
- 个人助手只读取当前阶段、下一步和未完成 P0 能力；全局搜索增加阶段与阶段参考项目。
- 页面加载、初始化和保存不访问招聘网站、GitHub 或模型。

## 接口与数据

新增 `POST /learning/stages/{stage_id}`。Career v6 增加学习路线、阶段、阶段参考仓库和阶段能力关系表，并为旧研读记录增加归档时间。

默认路线与阶段使用稳定 ID 幂等初始化。静态定义只更新标题、目标、范围和交付物，不覆盖作者保存的状态与证据。

## 兼容与回滚

原 Open Deep Research、FastAPI Starter、Onyx、OpenHands 和 Dify 记录仅增加归档标记，状态、Commit、测试结果和复盘保持原样；旧进度表单继续可用。Agent Reliability Arena 和旧学习任务继续从历史入口访问。

数据库升级前由统一迁移器建立快照。回滚时停止应用，恢复该快照并回退本批次代码。

## 验证结果

- Career 仓库、学习页与阶段表单定向测试通过。
- 助手上下文、页面烟雾测试通过。
- 完整 Pytest、Ruff、应用导入和安全守卫在批次完成时执行。

## 同步文档

- [求职与学习](../../features/career-learning.md)
- [求职学习指南](../../guides/career-workflow.md)
- [存储架构](../../architecture/storage.md)
