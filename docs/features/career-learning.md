# 求职与学习

## 定位与状态

状态：🟡 一期可用。该模块把候选人事实、真实项目证据、主简历、职位要求、技能差距和阶段制 Agent 工程学习路线连接起来，但不抓取招聘网站、不自动投递，也不会在学习页加载时访问 GitHub 或模型。

## 页面入口

| 入口 | 能力 |
|---|---|
| `/career` | 求职驾驶舱 |
| `/career/profile` | 候选人档案与导入确认 |
| `/career/documents` | 私有文档管理 |
| `/career/projects` | 真实项目证据库 |
| `/career/resumes` | 简历工作室：主简历、岗位定制、历史文件与待复核状态 |
| `/career/resumes/{id}` | 结构化编辑、私有照片、实时预览与双版本导出 |
| `/career/resumes/{id}/match/{job_id}` | 本地关键词覆盖与结构完整度报告 |
| `/career/jobs` | 职位和阶段时间线 |
| `/learning` | 单一五层 Agent 工程路线和阶段状态 |
| `/learning/history` | 只读查看旧路线、Commit、测试结果与复盘 |
| `/learning/maintenance` | 维护路线之外的技能和额外任务 |
| `/learning/campaigns/{id}` | 历史项目战役和证据 |

## 学习主线

```text
岗位 JD
→ 提取共性能力
→ 放入 Agent 工程框架
→ 按依赖顺序学习
→ 参考成熟开源项目
→ 手搓模块
→ 提交测试与复盘证据
```

默认页面只使用一套五层工程路线，不再并列展示“八层框架”和“四个阶段”：

1. **工程底座**：API、数据库、异步、Docker 和日志，作为已有基础，不计入进度。
2. **最小 Agent**：Model、Context、Tool、State 和 Stop。
3. **可靠 Runtime**：Loop、Sandbox、Approval、Trace 和 Recovery。
4. **状态化编排**：StateGraph、Checkpoint、Persistence 和 HITL。
5. **产品化交付**：RAG、Memory、MCP、Eval 和 Application。

后四层对应现有四个学习阶段，按掌握程度推进，不设置固定周期：

1. **手写最小 Agent**：不依赖框架，完成假模型、两个受限工具、最大步数、超时、轨迹和单元测试。
2. **拆 OpenHands**：研读 Loop、Runtime、Sandbox、权限、持久化和 Trace，手搓受限 Runtime、人工审批与轨迹回放。
3. **学 LangGraph**：掌握 State、Node、Edge、Checkpoint、Persistence 和 HITL，交付可暂停恢复的持久化工作流。
4. **看框架与产品化**：对照 AgentScope 与 Dify，整理架构笔记，并把 MCP 工具注册和权限层接入第三阶段项目。

主页面只修改阶段状态，不编辑 Commit、测试结果或私人复盘。已有证据继续保存在数据库并由 `/learning/history` 只读展示，状态更新不会覆盖这些字段。原 Open Deep Research、FastAPI Starter、Onyx、OpenHands 四周路线和 Agent Reliability Arena 战役只归档，不删除原有进度或证据。

## 求职与简历闭环

- 候选人档案只保存作者确认过的事实。
- 项目证据记录职责、技术栈、问题、行动、结果和量化证据。
- 作者从已有 PDF、DOCX、Markdown 或文本中明确选择一份，经本地提取预览和人工确认后建立唯一主简历；相同校验和的 DOCX 复用已有私有文档。
- 主简历使用结构化字段和单栏打印模板，可下载“国内照片版”和“无照片 ATS 版”。事实源变化只提示待复核，不自动覆盖表达。
- 本地 JD 报告展示关键词覆盖、缺失词和结构完整度，不承诺通过真实 ATS。
- 岗位定制创建主简历的子版本，永不覆盖主简历、档案或项目证据。

## 数据、模型与隐私

- 路线、阶段、阶段参考仓库、职位、技能和简历关系位于仓库外私有 `workspace.db`。
- 上传文档和简历照片使用随机存储名；照片只通过本地受保护路由读取。
- 学习页通过独立状态接口只修改目标阶段状态，不操作 GitHub，也不读取本地代码仓库。
- 个人助手只读取当前阶段、下一步和未完成 P0 能力，不读取完整私人复盘。
- 页面加载不会访问招聘网站、GitHub 或调用模型。
- 联系方式、简历正文、项目证据和照片不会进入公开路由、静态资源、全局搜索或手机快照。

## 当前限制与失败处理

- 路线不会自动判断“是否真的掌握”；“已验收”由作者手工确认。
- 岗位快照不会自动刷新；新岗位需手工录入并注明日期。
- 学历、论文、年限等非短期差距不会伪装成学习阶段。
- A2A/A2UI、微调和深入 K8s 保持 P2，不阻塞当前四阶段主线。
- 阶段保存使用事务；非法状态和不存在的阶段不会写入。

## 相关文档与测试

- [求职学习指南](../guides/career-workflow.md)
- [存储架构](../architecture/storage.md)
- [Agent 应用开发学习路线更新](../changes/2026/2026-08-28-agent-learning-path.md)
- [学习路线极简化](../changes/2026/2026-08-28-learning-roadmap-simplification.md)
- 简历流程参考 [Resume Matcher](https://github.com/srbhr/Resume-Matcher)（Apache-2.0），本项目按现有 FastAPI/Jinja2/SQLite 架构原生重写。
- 测试：`test_career.py`、`test_resume_studio.py`、`test_assistant.py`、`test_app.py`
