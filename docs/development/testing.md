# 测试与 CI

## 本地验证

```bash
WORKSPACE_DATA_DIR=/tmp/pcw-test-runtime .venv/bin/pytest -q
.venv/bin/ruff check app tests tools
.venv/bin/python tools/security_guards.py
.venv/bin/python tools/check_coverage_targets.py
WORKSPACE_DATA_DIR=/tmp/pcw-import .venv/bin/python -c "from app.asgi import app; print(app.title)"
```

定位问题时可以先运行相关测试文件，但功能批次交付前仍需完整验证。测试数量随项目变化，不作为永久文档契约。

## 测试分区

| 测试 | 领域 |
|---|---|
| `test_content.py`、`test_workspace.py` | Markdown、生命周期、周回顾和设置 |
| `test_knowledge*.py`、`test_obsidian.py` | 地图、卡片、来源、Revision、模板和迁移 |
| `test_publishing.py`、`test_wechat.py`、`test_video.py` | 微信转换、安全渲染、草稿箱直推、分镜和交接 |
| `test_career.py` | 档案、职位、文档、技能和学习路线 |
| `test_career_workspace.py` | 投递表局部更新、创建幂等、轮次状态、快照与照片保持、迁移回滚和安全边界 |
| `test_focus.py` | 阶段行动、重点上限、时区、隐私隔离和私有导入 |
| `test_daily_desk.py` | 快速待办、日期、撤销和仅详情行动过滤 |
| `test_daily_ai_workflow.py` | 今日待办、预览失效、并发派发、保存决策与验收 |
| `test_workflow_plugins.py` | 插件故障隔离、任务交接和真实 Autoloop 调度 |
| `test_income.py` | 固定收入来源、现金口径、迁移快照/回滚、表单、旧路由移除和移动隔离 |
| `test_model_gateway.py`、`test_llm.py` | Provider、上限、人工导入和用量 |
| `test_assistant.py` | 上下文隐私、白名单、摘要和行动幂等 |
| `test_mobile.py` | 配对、当日快照、离线编辑、冲突、图片和旧知识入口下线 |
| `test_library_search.py` | 材料和统一搜索 |
| `test_backup.py`、`test_database.py`、`test_recovery.py` | 加密、迁移、回滚和恢复 |
| `test_app.py` | 路由、安全中间件和跨模块烟雾测试 |
| `test_docs.py` | 文档结构、链接、更新档案和敏感信息 |
| `tests/browser/` | 桌面与移动关键浏览器流程 |

## CI 契约

- Python 3.13 为主版本，保留 Python 3.11 兼容验证。
- 使用锁定依赖和虚构隔离数据。
- 运行完整 Pytest、Ruff、文档校验、应用导入和安全守卫。
- 高风险模块逐项检查覆盖率，目标不低于 80%。
- Playwright 覆盖桌面阶段看板、创作、知识浏览和移动离线关键流程。

## 文档测试

文档测试递归扫描 `docs/**/*.md`，验证：

- 分类目录、索引和九个功能模块存在。
- 相对链接目标存在，单文件标题不重复。
- 更新记录 front matter 符合约定。
- README 中端口、数据目录和启动命令与代码一致。
- 文档不含真实邮箱、Tailnet 主机、私人绝对路径或密钥样例。
