---
date: 2026-10-20
status: completed
type: refactor
areas:
  - career
  - frontend
interfaces:
  - PATCH /career/jobs/{job_id}
  - POST /career/jobs
  - POST /career/jobs/{job_id}/submissions
data_migration: none
compatibility: existing form POSTs, detail pages and resume snapshots preserved
rollback: revert this feature batch; the database remains career v8
verification:
  - 285 full Pytest cases passed including browser acceptance
  - Ruff, isolated app import, security guards and diff whitespace checks
  - desktop and 390px and 320px autosave browser flows with fictional data
  - desktop LaunchAgent restarted and actual career page returned HTTP 200
commit: pending
---

# 投递表直接编辑与自动保存

## 背景与目标

移除投递表先点击编辑、再展开大表单的操作，让日常维护直接在单元格内完成。

## 最终行为

- 公司、岗位、进度、投递日期、下一步、跟进日期及备注直接可改。文字失焦保存，进度和日期变化后保存；每行显示简短的保存状态，失败保留输入并可重试。
- 同一行的请求串行处理并合并等待中的修改，不替换整行，不移动行位置或丢失焦点。筛选或页面内跳转前先完成待保存内容，失败留在原页面。浏览器强制刷新或直接关闭不提供额外弹窗，须先确认保存完成。
- 末行常驻空白记录，填完公司和岗位后自动创建，再出现下一行空白记录。响应丢失后重试使用相同创建标识，不重复创建职位或初始阶段事件。
- 简历列直接选择版本并点击“记录”，查看链接仍打开只读快照；普通自动保存不产生快照。
- JD、来源、地点和档位在“详情”的完整资料表单中维护，保留阶段时间线、定制和旧表单接口。

## 接口与数据

新增 `PATCH /career/jobs/{job_id}`，只接受投递表七个字段的局部 JSON 更新。在写事务中读取和验证当前记录，只更新实际变化的提交字段；状态变化和阶段事件保持同一事务。重复提交同一状态不重复追加事件，未提交的 JD、来源、地点及档位保持原值。

`POST /career/jobs` 支持 JSON 返回与客户端 UUID 创建标识；标识规范化后使用现有职位主键保证重复请求只创建一次，无新增表或迁移。普通表单 POST 继续兼容。投递快照 POST 支持 JSON 返回供原地更新链接，仍只在明确记录时追加快照。所有请求保留原 CSRF、Origin、Host 和本机访问校验。

## 兼容与回滚

简历工作室、定制流程、历史快照、旧 GET 入口与完整表单地址继续可用。数据库维持 Career v8，回滚本批次代码无需回退数据库；新建记录使用现有职位结构，原接口可继续维护。

## 验证结果

完整测试 285 项通过。新增覆盖局部更新保留其他资料、非法字段和日期、事务失败回滚、创建标识重试幂等、详情表单、CSRF 和跨站请求拒绝。浏览器覆盖直接自动保存、同一行连续修改合并、失败保留输入和重试、筛选前提交、创建成功但响应丢失后的重试、显式记录快照，以及桌面、390px 和 320px 操作。已核对截图，日期和操作列在桌面正常显示，窄屏仅表格内部横向滚动。

Ruff、隔离应用导入、安全守卫和差异空白检查通过。桌面常驻服务已重启，实际 `/career`、两个旧入口以及新版脚本和样式均返回 HTTP 200；真实环境只检查状态，不读取或展示私人页面正文。

## 同步文档

- [求职与学习功能](../../features/career-learning.md)
- [求职学习指南](../../guides/career-workflow.md)
- [存储架构](../../architecture/storage.md)
- [测试说明](../../development/testing.md)
