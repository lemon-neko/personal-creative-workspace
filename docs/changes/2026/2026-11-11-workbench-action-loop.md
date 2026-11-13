---
date: 2026-11-11
status: completed
type: feature
areas:
  - workspace
  - focus
  - agent-core
interfaces:
  - POST /focus/actions/{action_id}/local-task
  - /
  - /focus/goals/{goal_id}
  - /tasks
  - /runs
data_migration: agent_core v2 adds the focus action to task relation
compatibility: existing tasks, runs, focus records and old URLs remain valid
rollback: restore the pre-upgrade database snapshot before running code that only supports agent_core v1
verification:
  - 288 full Pytest cases including browser acceptance
  - Ruff, isolated application import, security guards and diff checks
  - desktop and narrow browser workflow with fictional data
  - restarted desktop service and verified HTTP 200 for the live workflow pages
commit: pending
---

# 工作台行动闭环

## 背景与目标

工作台原先分别展示阶段行动、运行轨迹和复盘。参考 [Agent Autoloop](https://github.com/KKKKhazix/agent-autoloop) 将执行与等待人工处理分开的做法，在现有本地运行时上接通这些入口。

## 最终行为

- 今日行动直达目标详情里的原行动。对首页可见且尚未完成或暂缓的行动，可以显式准备一条本地计划，再选择是否运行。
- 首页“等我处理”显示下个阶段决策和最多三条待验收、失败或待执行运行；独立任务也可在无阶段时进入这里。失败或取消后可以手工重新规划，历史记录保留。
- 任务和运行可回到原行动。验收只接受私有工作纸，原行动的完成状态仍由本人确认，再进入已有阶段复盘流程。
- 导航按工作流和资料工具分组；保留既有求职、学习、内容和设置入口。

## 接口与数据

新建任务和来源关系在同一事务写入，重复准备同一行动不会重复建任务。`agent_core` v2 只增加 `focus_action_tasks`，不改写原记录。来源目标切换为仅详情可见时，关联任务从首页、任务和运行总览移除。没有新增后台调度、模型调用或外部通知。

## 兼容与回滚

原 URL、独立任务和运行数据继续可用。统一迁移会保留升级前快照并在失败时回滚。若需要运行仅支持旧版本的代码，先恢复升级前数据库快照；恢复前应单独保留升级后新增的数据。

## 验证结果

完整 Pytest 288 项通过。浏览器使用虚构数据验证从今日行动进入、生成计划、执行、首页显示待验收、验收和返回原行动，检查桌面与窄屏。测试覆盖重复准备、失败后重规划、验收不改变原行动、隐私过滤、CSRF 和迁移回滚。Ruff、隔离应用导入、安全守卫及差异检查通过。桌面服务重启后，实际首页、阶段行动、阶段复盘、任务、运行和求职入口均返回 HTTP 200。

## 同步文档

- [工作台与内容](../../features/workspace-content.md)
- [阶段行动](../../features/focus.md)
- [本地任务运行时](../../features/agent-runtime.md)
- [阶段行动使用流程](../../guides/focus-workflow.md)
- [系统架构](../../architecture/README.md)和[存储架构](../../architecture/storage.md)
