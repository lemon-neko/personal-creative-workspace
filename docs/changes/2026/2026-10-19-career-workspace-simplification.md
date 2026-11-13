---
date: 2026-10-19
status: completed
type: feature
areas:
  - career
  - resumes
  - frontend
  - storage
interfaces:
  - /career
  - /career/jobs
  - /career/jobs/{job_id}/update
  - /career/jobs/{job_id}/submissions
  - /career/jobs/{job_id}/submissions/{submission_id}
  - /career/jobs/{job_id}/submissions/{submission_id}/photo
  - /career/resumes/{resume_id}/tailor
data_migration: career v7 to v8 via the existing unified migration registry
compatibility: existing job and resume detail, export and POST routes preserved
rollback: restore the pre-v8 database snapshot before reverting this feature batch
verification:
  - 281 full Pytest cases passed including browser acceptance
  - critical module coverage at least 80 percent
  - Ruff, isolated app import, security guards and diff whitespace checks
  - desktop, 390px and 320px browser flows and screenshot inspection
commit: pending
---

# 求职模块精简与投递进度表

## 背景与目标

减少求职首页的统计和跨模块入口，把主简历、岗位定制和公司投递进度放在同一页，支持日常快速维护。

## 最终行为

- `/career` 按简历工作室、定制简历、投递进度组织。主简历保留编辑与两种 PDF 导出；辅助资料默认折叠，学习与阶段行动保持独立。
- 投递表支持搜索、进度筛选、行内编辑与显式保存或取消。仅公司、岗位必填，JD 可后补；保存失败保留输入，成功保留筛选。默认隐藏归档记录，按最近更新排序。
- 笔试、一面、二面、终面与 HR 面使用独立状态；旧面试记录显示“面试中（未分轮次）”，不自动推断轮次或投递日期。只有实际阶段变化才记录时间线。
- 无 JD 可以复制主简历手工定制；本地匹配不展示无依据的报告，模型与人工模型任务接口要求先补 JD。
- 独立“记录此版本”操作保存实际投递简历的只读快照及历史。源简历正文、模板和照片的后续修改不改变已记录内容；普通投递字段保存不生成快照。

## 接口与数据

现有 `jobs` 与 `job_events` 继续使用。新增职位接口允许空 JD 和指定初始状态，行内更新接口事务性写入字段及阶段事件。新增快照记录、只读详情和受保护照片接口；只允许选择主简历或本岗位的定制版。Career v8 使用统一迁移序列新增 `job_resume_submissions`，旧数据不自动补造投递快照，照片清理同时检查快照引用。

快照冻结名称、目标岗位、Revision、结构化内容、模板、照片引用与记录时间，不保证复原外部发送 PDF 的文件字节。数据仍位于仓库外，快照不进入静态目录、搜索、助手或手机数据。

## 兼容与回滚

旧 `/career/resumes` 和 `/career/jobs` GET 地址跳转首页对应区域，职位详情、简历编辑、导出与原 POST 地址继续可用。既有用户记录和未提交代码保持保留。升级前统一迁移工具创建数据库备份，迁移失败时回滚；如需降级，必须先恢复升级前备份，再回退对应代码，不能让旧代码直接打开 v8 数据库。

## 验证结果

完整 Pytest 281 项通过，包含六项新增领域测试和一项新增浏览器流程；覆盖新增与错误回显、阶段变化、事务失败回滚、旧数据迁移、跨岗位简历拒绝、快照及照片保持、无 JD 模型边界和 CSRF／Origin／本地访问控制。浏览器检查包含桌面投递编辑、记录和查看快照、取消操作，以及 390px 和 320px 窄屏无页面溢出。人工核对桌面、窄屏编辑及快照截图。

关键模块覆盖率均达到 80%；Ruff、隔离应用导入、安全守卫与差异空白检查通过。全量测试记录了 SQLite 连接释放的 ResourceWarning，未造成测试失败。

常驻桌面服务曾因继续使用旧 Python 上下文、同时加载新模板而报 `filters is undefined`。已通过现有运行管理命令重启桌面服务，实际 `127.0.0.1:8765` 的 `/career`、两个旧入口及新增样式和脚本均返回 HTTP 200；检查只读取状态和响应头，不输出私人页面内容。运行维护和故障指南补充了更新后的重启与实际地址验证步骤。

## 同步文档

- [求职与学习功能](../../features/career-learning.md)
- [求职学习指南](../../guides/career-workflow.md)
- [存储架构](../../architecture/storage.md)
- [测试说明](../../development/testing.md)
