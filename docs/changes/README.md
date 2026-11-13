# 更新档案

本目录保存已经实现并完成验证的功能批次。它回答“某次更新为什么发生、最终改变了什么、怎样验证和回滚”，不替代功能文档、项目状态或 Git 历史。

## 记录规则

- 一个可独立验收的功能或重构批次对应一份记录，不要求每个 Git Commit 单独记录。
- 文件名固定为 `YYYY-MM-DD-short-name.md`，按年份归档。
- 记录只描述最终实现事实，不保存计划草稿、私人内容、真实邮箱、Tailnet 主机、密钥或数据正文。
- 功能事实以 `docs/features/` 为准；更新档案原则上保持稳定，后续只修正事实或补充 Commit/Tag。
- 新记录必须从 [模板](TEMPLATE.md) 创建，并加入下方索引。

## 当前记录

| 日期 | 类型 | 更新 | 涉及模块 |
|---|---|---|---|
| 2026-08-22 | baseline | [当前系统基线](2026/2026-08-22-baseline.md) | 全部模块 |
| 2026-08-22 | refactor | [内容分层与发布边界](2026/2026-08-22-content-layering.md) | 内容、知识、公众号、视频 |
| 2026-08-22 | docs | [文档体系重构](2026/2026-08-22-documentation-system.md) | 文档与测试 |
| 2026-08-22 | docs | [私有知识库目录说明](2026/2026-08-22-vault-folder-guide.md) | 知识库、Obsidian、文档 |
| 2026-08-23 | fix | [手机网关常驻修复](2026/2026-08-23-mobile-runtime-reliability.md) | 手机端、本机运行 |
| 2026-08-24 | feature | [悬赏收入一期](2026/2026-08-24-bounty-income.md) | 收入、助手、检索 |
| 2026-08-24 | feature | [商业与收入验证系统](2026/2026-08-24-business-validation.md) | 商业、收入、助手、检索 |
| 2026-08-24 | refactor | [收入面板极简重构](2026/2026-08-24-income-simplification.md) | 收入、助手、检索、迁移 |
| 2026-08-25 | feature | [Money Engine V1](2026/2026-08-25-money-engine-v1.md) | 收入、助手、首页、迁移 |
| 2026-08-25 | feature | [微信公众号草稿箱直推](2026/2026-08-25-wechat-draft-push.md) | 公众号、钥匙串、外发安全、迁移 |
| 2026-08-26 | refactor | [全站视觉系统升级](2026/2026-08-26-frontend-visual-system.md) | 前端、可访问性、响应式布局 |
| 2026-08-27 | feature | [简历工作室与岗位定制](2026/2026-08-27-resume-studio.md) | 求职、简历、模型网关、PDF、迁移 |
| 2026-08-27 | feature | [现有简历与照片导入](2026/2026-08-27-resume-photo-import.md) | 求职、简历、私有资产、PDF、迁移 |
| 2026-08-28 | refactor | [Agent 应用开发学习路线](2026/2026-08-28-agent-learning-path.md) | 求职学习、助手、检索、迁移 |
| 2026-08-28 | refactor | [学习路线极简化](2026/2026-08-28-learning-roadmap-simplification.md) | 求职学习、前端、文档 |
| 2026-08-31 | refactor | [赚钱验证闭环](2026/2026-08-31-money-skill-loop.md) | 收入、助手、迁移、文档 |
| 2026-09-02 | feature | [Agent Runtime Phase 1](2026/2026-09-02-agent-runtime-phase-1.md) | 任务、运行、本地检索、产物 |
| 2026-09-12 | refactor | [简历模板系统优化](2026/2026-09-12-resume-template-system.md) | 求职、简历、PDF、前端 |
| 2026-09-12 | refactor | [国内技术简历参考排版校准](2026/2026-09-12-resume-reference-layout.md) | 求职、简历、PDF、前端 |
| 2026-09-13 | refactor | [工作经历二层分区](2026/2026-09-13-resume-work-hierarchy.md) | 求职、简历、PDF、前端 |
| 2026-09-13 | refactor | [简历页眉图标与分区线](2026/2026-09-13-resume-header-icons.md) | 求职、简历、PDF、前端 |
| 2026-09-13 | refactor | [简历教育顺序与项目三层结构](2026/2026-09-13-resume-project-hierarchy.md) | 求职、简历、匹配、PDF、前端 |
| 2026-10-12 | feature | [阶段行动与首页看板](2026/2026-10-12-focus-dashboard.md) | 阶段行动、首页、求职、助手 |
| 2026-10-12 | refactor | [首页精简排版](2026/2026-10-12-home-layout-refinement.md) | 首页、阶段行动、前端 |
| 2026-10-19 | feature | [求职模块精简与投递进度表](2026/2026-10-19-career-workspace-simplification.md) | 求职、简历、前端、迁移 |
| 2026-10-20 | refactor | [投递表直接编辑与自动保存](2026/2026-10-20-career-table-autosave.md) | 求职、前端 |
| 2026-11-11 | feature | [工作台行动闭环](2026/2026-11-11-workbench-action-loop.md) | 首页、阶段行动、本地任务、迁移 |
| 2026-11-11 | feature | [今日看板与 AI 工作闭环](2026/2026-11-11-daily-board-ai-workflow.md) | 首页、阶段、AI、创作、知识、迁移 |
| 2026-11-11 | feature | [今日待办与安排交互](2026/2026-11-11-daily-task-interactions.md) | 首页、阶段、前端 |
| 2026-11-11 | refactor | [工作台视觉更新](2026/2026-11-11-workbench-editorial-ui.md) | 首页、导航、前端 |
| 2026-11-11 | feature | [日常工作与 AI 工作流窗口](2026/2026-11-11-calendar-and-agent-windows.md) | 日历、排程、AI、迁移 |
| 2026-11-11 | feature | [日常工作月历](2026/2026-11-11-planner-month-view.md) | 日历、前端 |
| 2026-11-12 | feature | [桌面工作台插件](2026/2026-11-12-workbench-plugins.md) | 日常工作、AI、插件 |
| 2026-11-12 | fix | [日常工作简体中文](2026/2026-11-12-daily-work-chinese.md) | 日常工作、中文 |
| 2026-11-12 | feature | [日常工作语言切换](2026/2026-11-12-daily-work-language-toggle.md) | 日常工作、中英文 |
| 2026-11-12 | refactor | [隐藏日常工作侧栏支持入口](2026/2026-11-12-daily-work-hide-support.md) | 日常工作、侧栏 |
| 2026-11-12 | feature | [AI 工作流控制中心](2026/2026-11-12-workflow-control-center.md) | 实时状态、追溯、人工决策 |
| 2026-11-12 | feature | [DeepSeek Harness 调度与归档](2026/2026-11-12-deepseek-workflow.md) | 工作流、模型执行 |
| 2026-11-12 | docs | [当前架构与数据流盘点](2026/2026-11-12-architecture-review.md) | 架构、技术栈、存储 |
| 2026-11-12 | refactor | [AI 工作流模块边界](2026/2026-11-12-workflow-boundaries.md) | 审批、派发、执行、恢复 |
| 2026-11-12 | refactor | [移动端日常工作与随手记](2026/2026-11-12-mobile-daily-capture.md) | Android PWA、日常工作、离线记录 |
| 2026-11-12 | refactor | [日常工作与 AI 插件故障隔离](2026/2026-11-12-plugin-startup-isolation.md) | 日常工作、AI 工作流、移动端 |
| 2026-11-12 | feature | [AI 工作流可观测性 V3](2026/2026-11-12-workflow-observability-v3.md) | AI 工作流、Trace、Agent 遥测 |
| 2026-11-13 | security | [公开源码准备](2026/2026-11-13-public-source.md) | 数据隔离、备份、桌面插件 |
| 2026-11-13 | docs | [Task 01 架构基线](2026/2026-11-13-architecture-baseline.md) | 架构、存储、依赖检查 |
| 2026-11-13 | refactor | [Task 02 桌面启动装配](2026/2026-11-13-application-bootstrap.md) | 桌面启动、依赖注入、资源生命周期 |

## 完成功能批次时

1. 更新对应功能文档。
2. 复制模板到当前年份目录，填写最终行为、接口、兼容、回滚和验证。
3. 把记录加入本页索引。
4. 若系统设计、用户步骤或成熟度变化，再更新对应公共文档。
5. 提交后可把 Commit SHA 或版本标签补入记录。
