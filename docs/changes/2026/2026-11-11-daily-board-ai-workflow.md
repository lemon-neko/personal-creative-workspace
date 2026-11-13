---
date: 2026-11-11
status: completed
type: feature
areas:
  - workbench
  - focus
  - agent-runtime
  - creation
  - knowledge
interfaces:
  - POST /today/events
  - POST /today/events/{id}/status
  - POST /today/events/{id}/agent
  - POST /runs/{id}/objective
  - POST /runs/{id}/ai
  - POST /runs/{id}/decision
data_migration: focus v3 and agent_core v3
compatibility: old routes and content preserved
rollback: preserve new data, then restore a pre-upgrade database with the previous code
verification:
  - full Pytest, including daily and AI workflow tests
  - isolated Chromium desktop and narrow viewport
  - Ruff, app import and security guard
  - live loopback status checks after desktop restart
commit: pending
---

## 今日看板与 AI 工作闭环

### 背景与目标

把工作台的起点统一为今日待办，减少分散入口，并让同一事项可以沿交接、决策、验收返回业务状态。

### 最终行为

- 首页可直接添加独立待办或挂到阶段交付物。今日重点、到期事项、今日完成和待确认运行在同一页；P0 主线与 P1/P2 分支显示行动完成数和下一交付。
- 交给 AI 后可补充任务材料。预览完整模型输入并确认；模型可以直接交付候选，或暂停等待一次人工决策。回答后再次确认才继续，产物由作者验收。
- 默认界面使用暖白底、低饱和青色和列表分区。侧栏保留五个常用入口；创作默认显示文章清单，知识库默认显示学科目录和最近卡片。
- 现有本地规则工作纸、公众号和视频、知识来源 Revision、求职与移动端流程保留。

### 接口与数据

`focus` v3 新增独立待办；`agent_core` v3 增加待办关联与运行决策。决策和暂停状态在同一事务写入；确认校验预览版本并独占派发。同一待办最多关联一个任务。所有新写入使用现有同源与 CSRF 校验；模型通过现有网关，完整提示词不进入运行日志。

### 兼容与回滚

未移动或覆盖现有内容。旧首页筛选链接、阶段行动、规则执行和旧求职链接保持兼容。需要回退应用时，先留存新版写入，再使用升级前快照和对应旧代码恢复。

### 验证结果

隔离测试覆盖独立待办、跨重启决策恢复、失效预览、重复派发、越界输出拒绝和人工验收。完整 Pytest 291 项通过，Chromium 检查桌面、窄屏与键盘操作。桌面服务重启后，今日、阶段、任务、运行、知识、创作与求职入口均返回 HTTP 200。没有使用真实私人资料调用模型。

### 同步文档

- [架构与流程](../../architecture/README.md)
- [私有存储](../../architecture/storage.md)
- [AI 工作](../../features/agent-runtime.md)
- [今日待办到复盘](../../guides/focus-workflow.md)
