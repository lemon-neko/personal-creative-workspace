# 桌面插件的安装、切换与恢复

需要 Node 24 或更新版本。使用独立的上游检出目录，固定版本并保留各自许可证。构建时会下载上游锁定的依赖，服务运行时从本地加载。

```sh
git clone --depth 1 --branch v20.0.0 https://github.com/super-productivity/super-productivity.git /tmp/workbench-super-productivity
git clone --depth 1 --branch v1.8.1 https://github.com/KKKKhazix/agent-autoloop.git /tmp/workbench-agent-autoloop
(cd /tmp/workbench-super-productivity && npm ci --ignore-scripts)
.venv/bin/python tools/build_workbench_web.py /tmp/workbench-super-productivity
.venv/bin/python -m app.install_plugins install --web /tmp/workbench-super-productivity/dist/browser --autoloop /tmp/workbench-agent-autoloop
.venv/bin/python -m app.install_plugins enable
.venv/bin/python -m app.runtime restart
```

更新已安装的日常工作 Web 资源时，构建后运行 `.venv/bin/python -m app.install_plugins refresh-web --web /tmp/workbench-super-productivity/dist/browser`，再重启桌面服务。此命令只替换 Web 资源及其校验值。

两个插件由桌面服务管理。本机 Web 资源监听 `localhost:8767`，Autoloop 监听 `127.0.0.1:8768`。请用 `http://127.0.0.1:8765/` 打开桌面工作台。插件版本及构建树 SHA-256 记录在应用数据目录的 `working/plugins/packages.json`。桌面启动时分别核对两个包。Web 包通过校验且服务可访问时才嵌入月历；Web 启动失败时可从首页打开旧待办。Autoloop 配置或执行后端损坏时可在 AI 工作流查看状态，日常工作可继续使用。

在桌面「设置 → 运行状态」查看 Web、Hub 和 Worker 的健康检查、重启次数和最近错误。Web 与 Autoloop 各自提供启动、停止和重启。自动恢复预算耗尽时，处理设置页提示后可手动启动。页面只展示经过过滤的日志；底层日志在私有数据目录的 `working/plugins/logs/`。

规则在 `working/plugins/autoloop-data/rules.json`，格式见 [Autoloop 协议](https://raw.githubusercontent.com/KKKKhazix/agent-autoloop/v1.8.1/docs/protocol.md)。编辑后，在插件目录运行以下命令校验。新规则的 `to` 使用 `gateway`，该接单程序只执行经确认的模型调用。

```sh
AGENT_AUTOLOOP_HOME="$PCW_PLUGINS/autoloop-data" node "$PCW_PLUGINS/autoloop/bin/agent-autoloop.ts" check
```

其中 `PCW_PLUGINS` 指应用数据目录下的 `working/plugins`。

- **备份**：Super Productivity 通过应用内导出保留任务和工时。在同一个工作台浏览器里导入可恢复。工作台数据库沿用现有 SQLite 备份流程。停止桌面服务后，额外备份整个 `working/plugins/autoloop-data` 与 `working/plugins/results`，保留原权限。引擎目录内的凭据随私有备份保存。
- **回退**：执行 `.venv/bin/python -m app.install_plugins disable`，然后重启桌面服务。两个主入口回到旧界面。原浏览器存储、Autoloop 状态、审批关联和产物仍在原处，重新启用可继续使用。
- **隔离验收**：设置 `WORKBENCH_E2E_WEB` 为 Web 构建目录，`WORKBENCH_E2E_ENGINE` 为 Autoloop 检出目录，运行 `pytest -q tests/test_workflow_plugins.py`。测试使用实际 Autoloop 和独立的随机本机端口，不启动第二个日常工作服务。

控制中心通过同源 SSE 使用 Autoloop 的日志游标，断线重连无需重启浏览器。备份和恢复时，`working/plugins/results` 中的 `*.answer.txt` 必须随数据库一起保留；它们与审批指纹关联。回退应用代码时保留这些文件和数据库备份，旧版无法继续处理尚未派发的文字回答。

### DeepSeek Harness

本机安装 DeepSeek Harness 后，在应用数据目录的 `working/plugins/harness.json` 写入 `{}`，重启桌面服务即可启用。默认使用 DeepSeek Harness 桌面应用附带的 `dsh` 和官方 `deepseek-flash` 模型。可通过配置中的 `executable` 和 `model` 指定其他已安装的 CLI 路径或 DeepSeek 模型。凭据来自进程中的 `DEEPSEEK_API_KEY`，或 DeepSeek Harness 本机凭据文件的同名配置。规则和工作项仍沿用原有入口。移走 `harness.json` 并重启即可切回工作台的默认模型网关。

工作流归档标记 `workflow-archive.json` 位于同一插件目录。备份时随工作台数据库和 Autoloop 原生日志保存。恢复旧列表时可移走该标记并刷新页面。已经通过 Autoloop 结案的卡片会保留结案事实。
